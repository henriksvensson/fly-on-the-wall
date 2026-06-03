from __future__ import annotations

import hashlib
import json
import re
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
    analysis_path: Path
    manifest_path: Path


def export_markdown_transcript(
    connection: Connection,
    meeting_id: str,
    transcript: str,
    analysis: str,
    storage: StoragePaths | None = None,
) -> ExportResult:
    meeting = connection.execute(
        """
        SELECT meetings.*, audio_metadata.recorded_at, audio_metadata.recorded_at_confidence
        FROM meetings
        LEFT JOIN audio_metadata ON audio_metadata.meeting_id = meetings.id
        WHERE meetings.id = ?
        """,
        (meeting_id,),
    ).fetchone()
    if meeting is None:
        raise ValueError(f"Meeting does not exist: {meeting_id}")

    export_id = str(uuid4())
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    paths = storage or storage_paths()
    output_dir = paths.exports / meeting["slug"] / f"{timestamp}-{export_id[:8]}"
    transcript_path = output_dir / "transcript.md"
    analysis_path = output_dir / "analysis.md"
    manifest_path = output_dir / "manifest.json"
    output_dir.mkdir(parents=True, exist_ok=False)

    markdown = _markdown_document(dict(meeting), transcript)
    transcript_path.write_text(markdown)
    analysis_markdown = analysis.strip() + "\n"
    analysis_path.write_text(analysis_markdown)
    manifest_path.write_text(
        json.dumps(
            {
                "id": export_id,
                "meeting_id": meeting_id,
                "format": "markdown",
                "transcript_path": str(transcript_path),
                "analysis_path": str(analysis_path),
                "transcript_sha256": _sha256(markdown),
                "analysis_sha256": _sha256(analysis_markdown),
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
    return ExportResult(export_id, output_dir, transcript_path, analysis_path, manifest_path)


def _markdown_document(meeting: dict, transcript: str) -> str:
    turns = _readable_turns(transcript)
    people = _participants(turns)
    date, time = _date_time(_meeting_timestamp(meeting))
    lines = [
        f"# {meeting['title']}",
        "",
        f"Date: {date}",
        f"Time: {time}",
        "Location: Unknown",
        "Position: Unknown",
        f"People: {', '.join(people) if people else 'Unknown'}",
        "",
        "## Transcript",
        "",
    ]
    for speaker, text in turns:
        lines.append(f"**{speaker}:** {text}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _readable_turns(transcript: str) -> list[tuple[str, str]]:
    unknown_speakers: dict[str, str] = {}
    turns: list[tuple[str, str]] = []
    for block in [block.strip() for block in transcript.split("\n\n") if block.strip()]:
        speaker, text, source_label = _parse_turn(block)
        if speaker == "Unknown":
            key = source_label or speaker
            if key not in unknown_speakers:
                unknown_speakers[key] = f"Unknown speaker {len(unknown_speakers) + 1}"
            speaker = unknown_speakers[key]
        turns.append((speaker, text))
    return turns


def _parse_turn(block: str) -> tuple[str, str, str | None]:
    speaker, separator, text = block.partition(":")
    if not separator:
        return "Unknown", block, None

    match = re.match(
        r"^(?P<name>.*?)(?:\s+\[[^\]]+\])?(?:\s+\((?P<source>[^)]+)\))?$",
        speaker.strip(),
    )
    if match is None:
        return speaker.strip() or "Unknown", text.strip(), None
    return match.group("name").strip() or "Unknown", text.strip(), match.group("source")


def _participants(turns: list[tuple[str, str]]) -> list[str]:
    participants: list[str] = []
    for speaker, _ in turns:
        if speaker not in participants:
            participants.append(speaker)
    return participants


def _date_time(created_at: str | None) -> tuple[str, str]:
    if not created_at:
        return "Unknown", "Unknown"
    date, _, time = created_at.partition(" ")
    return date or "Unknown", time or "Unknown"


def _meeting_timestamp(meeting: dict) -> str | None:
    if meeting.get("recorded_at_confidence") in {"high", "medium"}:
        return meeting.get("recorded_at")
    return meeting.get("created_at")


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()
