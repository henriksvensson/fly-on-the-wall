from __future__ import annotations

import hashlib
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from sqlite3 import Connection
from uuid import uuid4

from fly_on_the_wall.config import AppConfig
from fly_on_the_wall.storage import StoragePaths, ensure_storage_layout


@dataclass(frozen=True)
class Meeting:
    id: str
    slug: str
    title: str
    title_source: str
    language: str
    imported_audio_path: Path
    audio_sha256: str | None = None
    generated_title: str | None = None


@dataclass(frozen=True)
class DeleteMeetingResult:
    id: str
    slug: str
    removed_paths: tuple[Path, ...]


def import_meeting(
    connection: Connection,
    audio_path: Path,
    title: str | None,
    config: AppConfig,
    storage: StoragePaths | None = None,
    description: str | None = None,
) -> Meeting:
    if not audio_path.is_file():
        raise FileNotFoundError(f"Audio file does not exist: {audio_path}")

    audio_sha256 = file_sha256(audio_path)
    existing = get_meeting_by_audio_sha256(connection, audio_sha256)
    if existing is not None:
        return _meeting_from_row(existing)

    paths = storage or ensure_storage_layout()
    meeting_id = str(uuid4())
    provisional_title = title or audio_path.stem
    title_source = "manual" if title else "filename"
    slug = unique_slug(connection, slugify(provisional_title))
    imported_audio_path = paths.audio / slug / audio_path.name
    imported_audio_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(audio_path, imported_audio_path)

    with connection:
        connection.execute(
            """
            INSERT INTO meetings(
                id,
                slug,
                title,
                title_source,
                description,
                language,
                original_audio_path,
                imported_audio_path,
                audio_sha256
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                meeting_id,
                slug,
                provisional_title,
                title_source,
                description,
                config.language,
                str(audio_path),
                str(imported_audio_path),
                audio_sha256,
            ),
        )

    return Meeting(
        id=meeting_id,
        slug=slug,
        title=provisional_title,
        title_source=title_source,
        language=config.language,
        imported_audio_path=imported_audio_path,
        audio_sha256=audio_sha256,
    )


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "meeting"


def unique_slug(connection: Connection, base_slug: str) -> str:
    slug = base_slug
    suffix = 2
    while _slug_exists(connection, slug):
        slug = f"{base_slug}-{suffix}"
        suffix += 1
    return slug


def _slug_exists(connection: Connection, slug: str) -> bool:
    row = connection.execute("SELECT 1 FROM meetings WHERE slug = ?", (slug,)).fetchone()
    return row is not None


def list_meetings(connection: Connection) -> list[dict]:
    return [
        dict(row)
        for row in connection.execute(
            """
            SELECT id, slug, title, title_source, generated_title, language, created_at
            FROM meetings
            ORDER BY created_at DESC
            """
        ).fetchall()
    ]


def get_meeting(connection: Connection, meeting_id_or_slug: str) -> dict | None:
    row = connection.execute(
        """
        SELECT * FROM meetings
        WHERE id = ? OR slug = ?
        """,
        (meeting_id_or_slug, meeting_id_or_slug),
    ).fetchone()
    return None if row is None else dict(row)


def get_meeting_by_audio_sha256(connection: Connection, audio_sha256: str) -> dict | None:
    row = connection.execute(
        "SELECT * FROM meetings WHERE audio_sha256 = ?", (audio_sha256,)
    ).fetchone()
    return None if row is None else dict(row)


def latest_completed_provider_run(
    connection: Connection, meeting_id: str, provider: str = "elevenlabs"
) -> dict | None:
    row = connection.execute(
        """
        SELECT * FROM provider_runs
        WHERE meeting_id = ? AND provider = ? AND status = 'done'
        ORDER BY completed_at DESC, created_at DESC
        LIMIT 1
        """,
        (meeting_id, provider),
    ).fetchone()
    return None if row is None else dict(row)


def update_generated_title(connection: Connection, meeting_id: str, generated_title: str) -> None:
    normalized_title = generated_title.strip()
    if not normalized_title:
        return

    with connection:
        row = connection.execute(
            "SELECT title_source FROM meetings WHERE id = ?", (meeting_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"Meeting not found: {meeting_id}")

        if row["title_source"] == "manual":
            connection.execute(
                """
                UPDATE meetings
                SET generated_title = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (normalized_title, meeting_id),
            )
        else:
            connection.execute(
                """
                UPDATE meetings
                SET title = ?, title_source = 'generated', generated_title = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (normalized_title, normalized_title, meeting_id),
            )


def rename_meeting(connection: Connection, meeting_id_or_slug: str, title: str) -> dict:
    meeting = get_meeting(connection, meeting_id_or_slug)
    if meeting is None:
        raise ValueError(f"Meeting not found: {meeting_id_or_slug}")

    normalized_title = title.strip()
    if not normalized_title:
        raise ValueError("Meeting title cannot be empty.")

    with connection:
        connection.execute(
            """
            UPDATE meetings
            SET title = ?, title_source = 'manual', updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (normalized_title, meeting["id"]),
        )
    updated = get_meeting(connection, meeting["id"])
    if updated is None:
        raise ValueError(f"Meeting not found: {meeting_id_or_slug}")
    return updated


def _meeting_from_row(row: dict) -> Meeting:
    return Meeting(
        id=row["id"],
        slug=row["slug"],
        title=row["title"],
        title_source=row.get("title_source", "manual"),
        language=row["language"],
        imported_audio_path=Path(row["imported_audio_path"]),
        audio_sha256=row.get("audio_sha256"),
        generated_title=row.get("generated_title"),
    )


def meeting_stage_status(connection: Connection, meeting_id_or_slug: str) -> list[dict]:
    meeting = get_meeting(connection, meeting_id_or_slug)
    if meeting is None:
        return []
    return [
        dict(row)
        for row in connection.execute(
            """
            SELECT stage_name, status, error_message, updated_at
            FROM pipeline_stages
            WHERE meeting_id = ?
            ORDER BY stage_name
            """,
            (meeting["id"],),
        ).fetchall()
    ]


def delete_meeting(
    connection: Connection,
    meeting_id_or_slug: str,
    storage: StoragePaths | None = None,
) -> DeleteMeetingResult:
    meeting = get_meeting(connection, meeting_id_or_slug)
    if meeting is None:
        raise ValueError(f"Meeting not found: {meeting_id_or_slug}")

    paths = storage or ensure_storage_layout()
    removed_paths = _meeting_owned_paths(connection, meeting, paths)
    local_speaker_ids = _local_speaker_ids(connection, meeting["id"])
    voice_sample_ids = _meeting_voice_sample_ids(connection, meeting["id"])

    with connection:
        _delete_corrections(connection, meeting["id"], local_speaker_ids)
        _delete_voice_samples(connection, voice_sample_ids)
        connection.execute("DELETE FROM meetings WHERE id = ?", (meeting["id"],))

    for path in removed_paths:
        _remove_path(path)

    return DeleteMeetingResult(
        id=meeting["id"],
        slug=meeting["slug"],
        removed_paths=tuple(path for path in removed_paths if not path.exists()),
    )


def _meeting_owned_paths(
    connection: Connection, meeting: dict, storage: StoragePaths
) -> list[Path]:
    paths = [
        storage.audio / meeting["slug"],
        storage.artifacts / meeting["id"],
        storage.exports / meeting["slug"],
    ]

    for key in ("imported_audio_path",):
        if meeting.get(key):
            paths.append(Path(meeting[key]))

    for row in connection.execute(
        "SELECT output_dir, manifest_path FROM exports WHERE meeting_id = ?", (meeting["id"],)
    ).fetchall():
        paths.append(Path(row["output_dir"]))
        paths.append(Path(row["manifest_path"]))

    for row in connection.execute(
        """
        SELECT audio_path, embedding_path
        FROM voice_samples
        WHERE source_meeting_id = ?
        """,
        (meeting["id"],),
    ).fetchall():
        paths.append(Path(row["audio_path"]))
        if row["embedding_path"]:
            paths.append(Path(row["embedding_path"]))

    return _deduplicate_paths(paths)


def _local_speaker_ids(connection: Connection, meeting_id: str) -> list[str]:
    return [
        row["id"]
        for row in connection.execute(
            "SELECT id FROM local_speakers WHERE meeting_id = ?", (meeting_id,)
        ).fetchall()
    ]


def _meeting_voice_sample_ids(connection: Connection, meeting_id: str) -> list[str]:
    return [
        row["id"]
        for row in connection.execute(
            "SELECT id FROM voice_samples WHERE source_meeting_id = ?", (meeting_id,)
        ).fetchall()
    ]


def _delete_corrections(
    connection: Connection, meeting_id: str, local_speaker_ids: list[str]
) -> None:
    connection.execute("DELETE FROM corrections WHERE meeting_id = ?", (meeting_id,))
    if local_speaker_ids:
        placeholders = ", ".join("?" for _ in local_speaker_ids)
        connection.execute(
            f"DELETE FROM corrections WHERE local_speaker_id IN ({placeholders})",
            local_speaker_ids,
        )


def _delete_voice_samples(connection: Connection, voice_sample_ids: list[str]) -> None:
    if not voice_sample_ids:
        return
    placeholders = ", ".join("?" for _ in voice_sample_ids)
    connection.execute(
        f"DELETE FROM voice_samples WHERE id IN ({placeholders})",
        voice_sample_ids,
    )


def _remove_path(path: Path) -> None:
    if not path.exists():
        return
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()


def _deduplicate_paths(paths: list[Path]) -> list[Path]:
    seen: set[Path] = set()
    deduplicated: list[Path] = []
    for path in sorted(paths, key=lambda item: len(item.parts), reverse=True):
        resolved = path.expanduser()
        if resolved not in seen:
            seen.add(resolved)
            deduplicated.append(resolved)
    return deduplicated
