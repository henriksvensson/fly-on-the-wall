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
    language: str
    imported_audio_path: Path
    audio_sha256: str | None = None


def import_meeting(
    connection: Connection,
    audio_path: Path,
    title: str,
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
    slug = unique_slug(connection, slugify(title))
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
                description,
                language,
                original_audio_path,
                imported_audio_path,
                audio_sha256
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                meeting_id,
                slug,
                title,
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
        title=title,
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
            "SELECT id, slug, title, language, created_at FROM meetings ORDER BY created_at DESC"
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


def _meeting_from_row(row: dict) -> Meeting:
    return Meeting(
        id=row["id"],
        slug=row["slug"],
        title=row["title"],
        language=row["language"],
        imported_audio_path=Path(row["imported_audio_path"]),
        audio_sha256=row.get("audio_sha256"),
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
