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
from fly_on_the_wall.recording_quality import RecordingIgnoredError
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
    delete_originals_after_import: bool


@dataclass(frozen=True)
class WatchScanResult:
    seen: int
    processed: int
    ignored: int
    skipped: int
    failed: int


@dataclass(frozen=True)
class WatchFile:
    folder_id: str
    path: Path
    size_bytes: int
    mtime_ns: int
    mtime: float
    delete_original_after_import: bool


@dataclass(frozen=True)
class WatchFileResult:
    processed: int = 0
    ignored: int = 0
    skipped: int = 0
    failed: int = 0


@dataclass(frozen=True)
class WatchScanContext:
    connection: Connection
    config: AppConfig
    storage: StoragePaths | None
    process_fn: ProcessFn
    stable_age_seconds: int
    now: float
    progress: ProgressFn | None


def add_watch_folder(
    connection: Connection,
    path: Path,
    name: str | None = None,
    delete_originals_after_import: bool = False,
) -> WatchFolder:
    resolved_path = _resolve_folder_path(path)
    folder_id = str(uuid4())
    with connection:
        connection.execute(
            """
            INSERT INTO watch_folders(id, name, path, enabled, delete_originals_after_import)
            VALUES (?, ?, ?, 1, ?)
            """,
            (folder_id, name, str(resolved_path), 1 if delete_originals_after_import else 0),
        )
    return WatchFolder(folder_id, name, resolved_path, True, delete_originals_after_import)


def list_watch_folders(connection: Connection) -> list[WatchFolder]:
    return [
        _watch_folder_from_row(row)
        for row in connection.execute(
            """
            SELECT id, name, path, enabled, delete_originals_after_import
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
        SELECT id, name, path, enabled, delete_originals_after_import
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


def set_watch_folder_enabled(connection: Connection, identifier: str, enabled: bool) -> WatchFolder | None:
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
    return WatchFolder(folder.id, folder.name, folder.path, enabled, folder.delete_originals_after_import)


def set_watch_folder_delete_originals_after_import(
    connection: Connection,
    identifier: str,
    delete_originals_after_import: bool,
) -> WatchFolder | None:
    folder = get_watch_folder(connection, identifier)
    if folder is None:
        return None
    with connection:
        connection.execute(
            """
            UPDATE watch_folders
            SET delete_originals_after_import = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (1 if delete_originals_after_import else 0, folder.id),
        )
    return WatchFolder(folder.id, folder.name, folder.path, folder.enabled, delete_originals_after_import)


def scan_watch_folders(
    connection: Connection,
    config: AppConfig,
    storage: StoragePaths | None = None,
    process_fn: ProcessFn = process_audio,
    stable_age_seconds: int = DEFAULT_STABLE_AGE_SECONDS,
    progress: ProgressFn | None = None,
) -> WatchScanResult:
    seen = processed = ignored = skipped = failed = 0
    context = WatchScanContext(connection, config, storage, process_fn, stable_age_seconds, time.time(), progress)

    for folder in list_watch_folders(connection):
        if not folder.enabled:
            continue
        if not folder.path.is_dir():
            _report(progress, f"Skipping missing folder {folder.path}")
            continue

        for audio_path in _audio_files(folder.path):
            seen += 1
            result = _scan_audio_file(context, _watch_file(folder, audio_path))
            processed += result.processed
            ignored += result.ignored
            skipped += result.skipped
            failed += result.failed

    return WatchScanResult(seen=seen, processed=processed, ignored=ignored, skipped=skipped, failed=failed)


def _resolve_folder_path(path: Path) -> Path:
    return path.expanduser().resolve()


def _watch_folder_from_row(row) -> WatchFolder:
    return WatchFolder(
        id=row["id"],
        name=row["name"],
        path=Path(row["path"]),
        enabled=bool(row["enabled"]),
        delete_originals_after_import=bool(row["delete_originals_after_import"]),
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


def _watch_file(folder: WatchFolder, path: Path) -> WatchFile:
    stat = path.stat()
    return WatchFile(
        folder.id, path, stat.st_size, stat.st_mtime_ns, stat.st_mtime, folder.delete_originals_after_import
    )


def _scan_audio_file(
    context: WatchScanContext,
    item: WatchFile,
) -> WatchFileResult:
    was_seen_unchanged = _item_seen_unchanged(context.connection, item)
    _upsert_seen_item(context.connection, item)

    if not was_seen_unchanged and context.now - item.mtime < context.stable_age_seconds:
        _report(context.progress, f"Skipping recently modified file {item.path}")
        return WatchFileResult(skipped=1)

    if _item_final_for_current_file(context.connection, item):
        return WatchFileResult(skipped=1)

    return _process_audio_file(context, item)


def _process_audio_file(
    context: WatchScanContext,
    item: WatchFile,
) -> WatchFileResult:
    _report(context.progress, f"Processing {item.path}")
    _mark_item_processing(context.connection, item, file_sha256(item.path))
    try:
        result = context.process_fn(
            context.connection,
            item.path,
            None,
            context.config,
            storage=context.storage,
            progress=context.progress,
        )
    except RecordingIgnoredError as exc:
        _mark_item_ignored(context.connection, item.path, exc.meeting.id, exc.quality.reason)
        _report(context.progress, f"Ignored {item.path}: {exc.quality.reason}")
        return WatchFileResult(ignored=1)
    except Exception as exc:
        _mark_item_failed(context.connection, item.path, str(exc))
        _report(context.progress, f"Failed {item.path}: {exc}")
        return WatchFileResult(failed=1)

    _mark_item_done(context.connection, item.path, result.meeting.id)
    if item.delete_original_after_import:
        _delete_original_audio_file(item.path, result.meeting.imported_audio_path, context.progress)
    return WatchFileResult(processed=1)


def _delete_original_audio_file(original_path: Path, imported_audio_path: Path, progress: ProgressFn | None) -> None:
    if original_path.resolve() == imported_audio_path.resolve():
        _report(progress, f"Keeping original because it is the imported audio file {original_path}")
        return
    try:
        original_path.unlink()
    except FileNotFoundError:
        return
    except OSError as exc:
        _report(progress, f"Could not delete original audio file {original_path}: {exc}")
        return
    _report(progress, f"Deleted original audio file {original_path}")


def _upsert_seen_item(connection: Connection, item: WatchFile) -> None:
    existing = _watch_item(connection, item.path)
    with connection:
        if existing is None:
            connection.execute(
                """
                INSERT INTO watch_items(id, folder_id, path, size_bytes, mtime_ns, status)
                VALUES (?, ?, ?, ?, ?, 'pending')
                """,
                (str(uuid4()), item.folder_id, str(item.path), item.size_bytes, item.mtime_ns),
            )
            return

        if existing["size_bytes"] != item.size_bytes or existing["mtime_ns"] != item.mtime_ns:
            connection.execute(
                """
                UPDATE watch_items
                SET folder_id = ?, size_bytes = ?, mtime_ns = ?, status = 'pending',
                    error_message = NULL, last_seen_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE path = ?
                """,
                (item.folder_id, item.size_bytes, item.mtime_ns, str(item.path)),
            )
        else:
            connection.execute(
                """
                UPDATE watch_items
                SET folder_id = ?, last_seen_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                WHERE path = ?
                """,
                (item.folder_id, str(item.path)),
            )


def _item_final_for_current_file(connection: Connection, file: WatchFile) -> bool:
    item = _watch_item(connection, file.path)
    return bool(
        item is not None
        and item["status"] in {"done", "ignored"}
        and item["size_bytes"] == file.size_bytes
        and item["mtime_ns"] == file.mtime_ns
    )


def _item_seen_unchanged(connection: Connection, file: WatchFile) -> bool:
    item = _watch_item(connection, file.path)
    return bool(item is not None and item["size_bytes"] == file.size_bytes and item["mtime_ns"] == file.mtime_ns)


def _mark_item_processing(connection: Connection, item: WatchFile, file_hash: str) -> None:
    with connection:
        connection.execute(
            """
            UPDATE watch_items
            SET file_sha256 = ?, size_bytes = ?, mtime_ns = ?, status = 'processing',
                error_message = NULL, updated_at = CURRENT_TIMESTAMP
            WHERE path = ?
            """,
            (file_hash, item.size_bytes, item.mtime_ns, str(item.path)),
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


def _mark_item_ignored(connection: Connection, path: Path, meeting_id: str, reason: str) -> None:
    with connection:
        connection.execute(
            """
            UPDATE watch_items
            SET status = 'ignored', meeting_id = ?, error_message = ?,
                processed_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
            WHERE path = ?
            """,
            (meeting_id, reason, str(path)),
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
