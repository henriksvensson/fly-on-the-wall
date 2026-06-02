from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from sqlite3 import Connection
from uuid import uuid4

from fly_on_the_wall.storage import StoragePaths, storage_paths


@dataclass(frozen=True)
class ExportResult:
    id: str
    output_dir: Path
    transcript_path: Path
    manifest_path: Path


def export_markdown_transcript(
    connection: Connection,
    meeting_id: str,
    transcript: str,
    storage: StoragePaths | None = None,
) -> ExportResult:
    meeting = connection.execute(
        "SELECT slug, title FROM meetings WHERE id = ?", (meeting_id,)
    ).fetchone()
    if meeting is None:
        raise ValueError(f"Meeting does not exist: {meeting_id}")

    export_id = str(uuid4())
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    paths = storage or storage_paths()
    output_dir = paths.exports / meeting["slug"] / f"{timestamp}-{export_id[:8]}"
    transcript_path = output_dir / "transcript.md"
    manifest_path = output_dir / "manifest.json"
    output_dir.mkdir(parents=True, exist_ok=False)

    markdown = _markdown_document(meeting["title"], transcript)
    transcript_path.write_text(markdown)
    manifest_path.write_text(
        json.dumps(
            {
                "id": export_id,
                "meeting_id": meeting_id,
                "format": "markdown",
                "transcript_path": str(transcript_path),
                "sha256": _sha256(markdown),
            },
            indent=2,
        )
        + "\n"
    )

    with connection:
        connection.execute(
            """
            INSERT INTO exports(id, meeting_id, format, output_dir, manifest_path)
            VALUES (?, ?, ?, ?, ?)
            """,
            (export_id, meeting_id, "markdown", str(output_dir), str(manifest_path)),
        )
    return ExportResult(export_id, output_dir, transcript_path, manifest_path)


def _markdown_document(title: str, transcript: str) -> str:
    return f"# {title}\n\n## Transcript\n\n{transcript.strip()}\n"


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()
