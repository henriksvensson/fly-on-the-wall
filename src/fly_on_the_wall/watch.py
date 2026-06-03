from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from sqlite3 import Connection
from uuid import uuid4

from fly_on_the_wall.config import AppConfig
from fly_on_the_wall.meetings import file_sha256
from fly_on_the_wall.processing import ProcessResult, process_audio
from fly_on_the_wall.storage import StoragePaths

AUDIO_EXTENSIONS = frozenset({".aac", ".caf", ".m4a", ".mp3", ".wav"})
DEFAULT_STABLE_AGE_SECONDS = 5
TEMP_SUFFIXES = (".crdownload", ".download", ".part", ".tmp")

ProgressFn = Callable[[str], None]
ProcessFn = Callable[..., ProcessResult]


@dataclass(frozen=True)
class WatchFolder:
    id: str
    name: str | None
    path: Path
    enabled: bool


@dataclass(frozen=True)
class WatchScanResult:
    seen: int
    processed: int
    skipped: int
    failed: int


def add_watch_folder(connection: Connection, path: Path, name: str | None = None) -> WatchFolder:
    resolved_path = _resolve_folder_path(path)
    folder_id = str(uuid4())
    with connection:
        connection.execute(
            """
            INSERT INTO watch_folders(id, name, path, enabled)
            VALUES (?, ?, ?, 1)
            """,
            (folder_id, name, str(resolved_path)),
        )
    return WatchFolder(folder_id, name, resolved_path, True)


def list_watch_folders(connection: Connection) -> list[WatchFolder]:
    return [
        _watch_folder_from_row(row)
        for row in connection.execute(
            """
            SELECT id, name, path, enabled
            FROM watch_folders
            ORDER BY created_at, path
            """
        ).fetchall()
    ]


def get_watch_folder(connection: Connection, identifier: str) -> WatchFolder | None:
    identifier_path = str(Path(identifier).expanduser())
    resolved_identifier_path = str(Path(identifier).expanduser().resolve())
    row = connection.execute(
        """
        SELECT id, name, path, enabled
        FROM watch_folders
        WHERE id = ? OR name = ? OR path = ? OR path = ?
        """,
        (identifier, identifier, identifier_path, resolved_identifier_path),
    ).fetchone()
    return None if row is None else _watch_folder_from_row(row)


def remove_watch_folder(connection: Connection, identifier: str) -> WatchFolder | None:
    folder = get_watch_folder(connection, identifier)
    if folder is None:
        return None
    with connection:
        connection.execute("DELETE FROM watch_folders WHERE id = ?", (folder.id,))
    return folder


def set_watch_folder_enabled(
    connection: Connection, identifier: str, enabled: bool
) -> WatchFolder | None:
    folder = get_watch_folder(connection, identifier)
    if folder is None:
        return None
    with connection:
        connection.execute(
            """
            UPDATE watch_folders
            SET enabled = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (1 if enabled else 0, folder.id),
        )
    return WatchFolder(folder.id, folder.name, folder.path, enabled)


def scan_watch_folders(
    connection: Connection,
    config: AppConfig,
    storage: StoragePaths | None = None,
    process_fn: ProcessFn = process_audio,
    stable_age_seconds: int = DEFAULT_STABLE_AGE_SECONDS,
    progress: ProgressFn | None = None,
) -> WatchScanResult:
    seen = processed = skipped = failed = 0
    now = time.time()

    for folder in list_watch_folders(connection):
        if not folder.enabled:
            continue
        if not folder.path.is_dir():
            _report(progress, f"Skipping missing folder {folder.path}")
            continue

        for audio_path in _audio_files(folder.path):
            seen += 1
            stat = audio_path.stat()
            _upsert_seen_item(connection, folder.id, audio_path, stat.st_size, stat.st_mtime_ns)

            if now - stat.st_mtime < stable_age_seconds:
                skipped += 1
                _report(progress, f"Skipping recently modified file {audio_path}")
                continue

            if _item_done_for_current_file(connection, audio_path, stat.st_size, stat.st_mtime_ns):
                skipped += 1
                continue

            _report(progress, f"Processing {audio_path}")
            audio_hash = file_sha256(audio_path)
            _mark_item_processing(
                connection, audio_path, audio_hash, stat.st_size, stat.st_mtime_ns
            )
            try:
                result = process_fn(
                    connection,
                    audio_path,
                    None,
                    config,
                    storage=storage,
                    progress=progress,
                )
            except Exception as exc:
                failed += 1
                _mark_item_failed(connection, audio_path, str(exc))
                _report(progress, f"Failed {audio_path}: {exc}")
                continue

            processed += 1
            _mark_item_done(connection, audio_path, result.meeting.id)

    return WatchScanResult(seen=seen, processed=processed, skipped=skipped, failed=failed)


def _resolve_folder_path(path: Path) -> Path:
    resolved_path = path.expanduser().resolve()
    if not resolved_path.is_dir():
        raise FileNotFoundError(f"Watch folder does not exist: {resolved_path}")
    return resolved_path


def _watch_folder_from_row(row) -> WatchFolder:
    return WatchFolder(
        id=row["id"],
        name=row["name"],
        path=Path(row["path"]),
        enabled=bool(row["enabled"]),
    )


def _audio_files(folder: Path) -> Iterable[Path]:
    for path in sorted(folder.rglob("*")):
        if not path.is_file():
            continue
        if path.name.startswith("."):
            continue
        if path.suffix.lower() not in AUDIO_EXTENSIONS:
            continue
        if path.name.lower().endswith(TEMP_SUFFIXES):
            continue
        yield path


def _upsert_seen_item(
    connection: Connection, folder_id: str, path: Path, size_bytes: int, mtime_ns: int
) -> None:
    existing = _watch_item(connection, path)
    with connection:
        if existing is None:
            connection.execute(
                """
                INSERT INTO watch_items(id, folder_id, path, size_bytes, mtime_ns, status)
                VALUES (?, ?, ?, ?, ?, 'pending')
                """,
                (str(uuid4()), folder_id, str(path), size_bytes, mtime_ns),
            )
            return

        if existing["size_bytes"] != size_bytes or existing["mtime_ns"] != mtime_ns:
            connection.execute(
                """
                UPDATE watch_items
                SET folder_id = ?, size_bytes = ?, mtime_ns = ?, status = 'pending',
                    error_message = NULL, last_seen_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE path = ?
                """,
                (folder_id, size_bytes, mtime_ns, str(path)),
            )
        else:
            connection.execute(
                """
                UPDATE watch_items
                SET folder_id = ?, last_seen_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                WHERE path = ?
                """,
                (folder_id, str(path)),
            )


def _item_done_for_current_file(
    connection: Connection, path: Path, size_bytes: int, mtime_ns: int
) -> bool:
    item = _watch_item(connection, path)
    return bool(
        item is not None
        and item["status"] == "done"
        and item["size_bytes"] == size_bytes
        and item["mtime_ns"] == mtime_ns
    )


def _mark_item_processing(
    connection: Connection, path: Path, file_hash: str, size_bytes: int, mtime_ns: int
) -> None:
    with connection:
        connection.execute(
            """
            UPDATE watch_items
            SET file_sha256 = ?, size_bytes = ?, mtime_ns = ?, status = 'processing',
                error_message = NULL, updated_at = CURRENT_TIMESTAMP
            WHERE path = ?
            """,
            (file_hash, size_bytes, mtime_ns, str(path)),
        )


def _mark_item_done(connection: Connection, path: Path, meeting_id: str) -> None:
    with connection:
        connection.execute(
            """
            UPDATE watch_items
            SET status = 'done', meeting_id = ?, error_message = NULL,
                processed_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
            WHERE path = ?
            """,
            (meeting_id, str(path)),
        )


def _mark_item_failed(connection: Connection, path: Path, error_message: str) -> None:
    with connection:
        connection.execute(
            """
            UPDATE watch_items
            SET status = 'failed', error_message = ?, updated_at = CURRENT_TIMESTAMP
            WHERE path = ?
            """,
            (error_message, str(path)),
        )


def _watch_item(connection: Connection, path: Path):
    return connection.execute("SELECT * FROM watch_items WHERE path = ?", (str(path),)).fetchone()


def _report(progress: ProgressFn | None, message: str) -> None:
    if progress is not None:
        progress(message)
