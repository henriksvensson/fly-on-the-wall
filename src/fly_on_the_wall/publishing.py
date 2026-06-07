from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from sqlite3 import Connection
from uuid import uuid4


@dataclass(frozen=True)
class PublishTarget:
    id: str
    name: str
    target_type: str
    path: Path
    auto_publish: bool
    enabled: bool
    settings: dict


@dataclass(frozen=True)
class PublishResult:
    target: PublishTarget
    output_path: Path
    content_sha256: str


def add_publish_target(
    connection: Connection,
    target_type: str,
    path: Path,
    name: str,
    auto_publish: bool = False,
    enabled: bool = True,
    settings: dict | None = None,
) -> PublishTarget:
    if target_type != "obsidian":
        raise ValueError(f"Unsupported publish target type: {target_type}")

    target_id = str(uuid4())
    resolved_path = path.expanduser().resolve()
    with connection:
        connection.execute(
            """
            INSERT INTO publish_targets(
                id, name, target_type, path, settings_json, auto_publish, enabled
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                target_id,
                name,
                target_type,
                str(resolved_path),
                json.dumps(settings or {}, sort_keys=True),
                1 if auto_publish else 0,
                1 if enabled else 0,
            ),
        )
    return PublishTarget(target_id, name, target_type, resolved_path, auto_publish, enabled, settings or {})


def list_publish_targets(connection: Connection) -> list[PublishTarget]:
    return [
        _target_from_row(row)
        for row in connection.execute(
            """
            SELECT * FROM publish_targets
            ORDER BY created_at, name
            """
        ).fetchall()
    ]


def get_publish_target(connection: Connection, identifier: str) -> PublishTarget | None:
    row = connection.execute(
        """
        SELECT * FROM publish_targets
        WHERE id = ? OR name = ?
        """,
        (identifier, identifier),
    ).fetchone()
    return None if row is None else _target_from_row(row)


def remove_publish_target(connection: Connection, identifier: str) -> PublishTarget | None:
    target = get_publish_target(connection, identifier)
    if target is None:
        return None
    with connection:
        connection.execute("DELETE FROM publish_targets WHERE id = ?", (target.id,))
    return target


def set_publish_target_enabled(connection: Connection, identifier: str, enabled: bool) -> PublishTarget | None:
    target = get_publish_target(connection, identifier)
    if target is None:
        return None
    with connection:
        connection.execute(
            """
            UPDATE publish_targets
            SET enabled = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (1 if enabled else 0, target.id),
        )
    return PublishTarget(
        target.id,
        target.name,
        target.target_type,
        target.path,
        target.auto_publish,
        enabled,
        target.settings,
    )


def publish_meeting(connection: Connection, meeting_id_or_slug: str, target_identifier: str) -> PublishResult:
    target = get_publish_target(connection, target_identifier)
    if target is None:
        raise ValueError(f"Publish target not found: {target_identifier}")
    if not target.enabled:
        raise ValueError(f"Publish target is disabled: {target.name}")
    if target.target_type != "obsidian":
        raise ValueError(f"Unsupported publish target type: {target.target_type}")

    meeting = _meeting_with_metadata(connection, meeting_id_or_slug)
    export = _latest_export(connection, meeting["id"])
    transcript_path, analysis_path, manifest_path = _export_paths(export)
    transcript_markdown = transcript_path.read_text()
    analysis_markdown = _read_analysis_markdown(analysis_path)
    manifest = json.loads(manifest_path.read_text())
    output_path = _published_output_path(connection, meeting, target)
    content = _obsidian_note(meeting, transcript_markdown, analysis_markdown, manifest)
    content_hash = _sha256(content)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content)
    _upsert_published_item(connection, meeting["id"], target.id, output_path, content_hash)
    return PublishResult(target, output_path, content_hash)


def publish_all_meetings(
    connection: Connection, target_identifier: str, only_unpublished: bool = False
) -> list[PublishResult]:
    target = get_publish_target(connection, target_identifier)
    if target is None:
        raise ValueError(f"Publish target not found: {target_identifier}")

    results: list[PublishResult] = []
    for meeting_id in _publishable_meeting_ids(connection, target.id, only_unpublished):
        results.append(publish_meeting(connection, meeting_id, target.id))
    return results


def publish_enabled_targets(connection: Connection, meeting_id: str) -> list[PublishResult]:
    results: list[PublishResult] = []
    for target in list_publish_targets(connection):
        if target.enabled and target.auto_publish:
            results.append(publish_meeting(connection, meeting_id, target.id))
    return results


def _publishable_meeting_ids(connection: Connection, target_id: str, only_unpublished: bool) -> list[str]:
    rows = connection.execute(
        """
        SELECT meetings.id
        FROM meetings
        WHERE EXISTS (
            SELECT 1 FROM exports
            WHERE exports.meeting_id = meetings.id AND exports.format = 'markdown'
        )
        AND (
            ? = 0 OR NOT EXISTS (
                SELECT 1 FROM published_items
                WHERE published_items.meeting_id = meetings.id
                  AND published_items.target_id = ?
            )
        )
        ORDER BY meetings.created_at
        """,
        (1 if only_unpublished else 0, target_id),
    ).fetchall()
    return [row["id"] for row in rows]


def _target_from_row(row) -> PublishTarget:
    return PublishTarget(
        id=row["id"],
        name=row["name"],
        target_type=row["target_type"],
        path=Path(row["path"]),
        auto_publish=bool(row["auto_publish"]),
        enabled=bool(row["enabled"]),
        settings=json.loads(row["settings_json"] or "{}"),
    )


def _meeting_with_metadata(connection: Connection, meeting_id_or_slug: str) -> dict:
    row = connection.execute(
        """
        SELECT meetings.*, audio_metadata.recorded_at, audio_metadata.recorded_at_confidence,
               audio_metadata.duration_seconds, audio_metadata.device_or_software,
               recording_quality.status AS recording_quality_status,
               recording_quality.reason AS recording_quality_reason
        FROM meetings
        LEFT JOIN audio_metadata ON audio_metadata.meeting_id = meetings.id
        LEFT JOIN recording_quality ON recording_quality.meeting_id = meetings.id
        WHERE meetings.id = ? OR meetings.slug = ?
        """,
        (meeting_id_or_slug, meeting_id_or_slug),
    ).fetchone()
    if row is None:
        raise ValueError(f"Meeting not found: {meeting_id_or_slug}")
    return dict(row)


def _latest_export(connection: Connection, meeting_id: str) -> dict:
    row = connection.execute(
        """
        SELECT exports.*, rowid
        FROM exports
        WHERE meeting_id = ? AND format = 'markdown'
        ORDER BY created_at DESC, rowid DESC
        LIMIT 1
        """,
        (meeting_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"No markdown export found for meeting: {meeting_id}")
    return dict(row)


def _export_paths(export: dict) -> tuple[Path, Path | None, Path]:
    manifest_path = Path(export["manifest_path"])
    manifest = json.loads(manifest_path.read_text())
    transcript_path = Path(manifest.get("transcript_path") or manifest_path.parent / "transcript.md")
    analysis_path = _optional_manifest_path(manifest, "analysis_path", manifest_path.parent / "analysis.md")
    return transcript_path, analysis_path, manifest_path


def _optional_manifest_path(manifest: dict, key: str, fallback: Path) -> Path | None:
    if manifest.get(key):
        return Path(manifest[key])
    if fallback.exists():
        return fallback
    return None


def _read_analysis_markdown(analysis_path: Path | None) -> str:
    if analysis_path is not None and analysis_path.exists():
        return analysis_path.read_text()
    return "# Meeting Analysis\n\n## Summary\n\nNo analysis export found for this snapshot."


def _published_output_path(connection: Connection, meeting: dict, target: PublishTarget) -> Path:
    row = connection.execute(
        """
        SELECT output_path FROM published_items
        WHERE meeting_id = ? AND target_id = ?
        """,
        (meeting["id"], target.id),
    ).fetchone()
    if row is not None:
        return Path(row["output_path"])

    date = _meeting_date(meeting)
    filename = _safe_filename(f"{date} {meeting['title']}.md")
    return target.path / filename


def _obsidian_note(meeting: dict, transcript_markdown: str, analysis_markdown: str, manifest: dict) -> str:
    date, time = _date_time(_meeting_timestamp(meeting))
    frontmatter = {
        "title": meeting["title"],
        "date": date,
        "time": time,
        "source": "fly-on-the-wall",
        "meeting_id": meeting["id"],
        "slug": meeting["slug"],
        "title_source": meeting.get("title_source"),
        "recorded_at": meeting.get("recorded_at"),
        "duration_seconds": meeting.get("duration_seconds"),
        "recording_quality": meeting.get("recording_quality_status"),
        "tags": ["meetings", "fly-on-the-wall"],
    }
    lines = ["---", *_yaml_lines(frontmatter), "---", ""]
    lines.append("<!-- This note is managed by Fly on the Wall. Republishing may overwrite changes. -->")
    lines.append("")
    lines.append(f"# {meeting['title']}")
    lines.append("")
    lines.append("## Details")
    lines.append("")
    lines.append(f"Date: {date}")
    lines.append(f"Time: {time}")
    if meeting.get("duration_seconds") is not None:
        lines.append(f"Duration: {_format_duration(float(meeting['duration_seconds']))}")
    if meeting.get("device_or_software"):
        lines.append(f"Device/Software: {meeting['device_or_software']}")
    if meeting.get("recording_quality_status"):
        lines.append(
            f"Recording Quality: {meeting['recording_quality_status']} ({meeting['recording_quality_reason']})"
        )
    lines.append(f"Internal Export: {manifest.get('id', 'unknown')}")
    lines.append("")
    lines.append("## Analysis")
    lines.append("")
    lines.append(_strip_top_heading(analysis_markdown, "Meeting Analysis"))
    lines.append("")
    lines.append("## Manuscript")
    lines.append("")
    lines.append(_strip_transcript_heading(transcript_markdown))
    return "\n".join(lines).rstrip() + "\n"


def _yaml_lines(values: dict) -> list[str]:
    lines: list[str] = []
    for key, value in values.items():
        if value is None:
            continue
        if isinstance(value, list):
            lines.append(f"{key}:")
            lines.extend(f"  - {_yaml_scalar(item)}" for item in value)
        else:
            lines.append(f"{key}: {_yaml_scalar(value)}")
    return lines


def _yaml_scalar(value: object) -> str:
    text = str(value)
    if re.search(r"[:#\n,]", text):
        return json.dumps(text, ensure_ascii=False)
    return text


def _strip_top_heading(markdown: str, heading: str) -> str:
    lines = markdown.strip().splitlines()
    if lines and lines[0].strip() == f"# {heading}":
        return "\n".join(lines[1:]).strip()
    return markdown.strip()


def _strip_transcript_heading(markdown: str) -> str:
    lines = markdown.strip().splitlines()
    if lines and lines[0].startswith("# "):
        lines = lines[1:]
    while lines and lines[0].strip() not in {"## Transcript", "## Manuscript"}:
        lines.pop(0)
    if lines and lines[0].strip() in {"## Transcript", "## Manuscript"}:
        lines.pop(0)
    return "\n".join(lines).strip()


def _meeting_timestamp(meeting: dict) -> str | None:
    if meeting.get("recorded_at_confidence") in {"high", "medium"}:
        return meeting.get("recorded_at")
    return meeting.get("created_at")


def _meeting_date(meeting: dict) -> str:
    date, _ = _date_time(_meeting_timestamp(meeting))
    return date if date != "Unknown" else "undated"


def _date_time(value: str | None) -> tuple[str, str]:
    if not value:
        return "Unknown", "Unknown"
    date, _, time = value.partition(" ")
    return date or "Unknown", time or "Unknown"


def _format_duration(seconds: float) -> str:
    total_seconds = int(seconds)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes}m {seconds}s"
    if minutes:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


def _safe_filename(value: str) -> str:
    safe = re.sub(r"[\\/:*?\"<>|]+", "-", value).strip()
    return safe or "meeting.md"


def _upsert_published_item(
    connection: Connection, meeting_id: str, target_id: str, output_path: Path, content_hash: str
) -> None:
    with connection:
        connection.execute(
            """
            INSERT INTO published_items(
                id, meeting_id, target_id, output_path, content_sha256
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(meeting_id, target_id) DO UPDATE SET
                output_path = excluded.output_path,
                content_sha256 = excluded.content_sha256,
                published_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            """,
            (str(uuid4()), meeting_id, target_id, str(output_path), content_hash),
        )


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()
