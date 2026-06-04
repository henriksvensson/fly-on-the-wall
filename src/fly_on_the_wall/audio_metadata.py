from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from sqlite3 import Connection

from fly_on_the_wall.audio import AudioError, probe_metadata
from fly_on_the_wall.storage import StoragePaths


@dataclass(frozen=True)
class NormalizedAudioMetadata:
    recorded_at: str | None = None
    recorded_at_source: str | None = None
    recorded_at_confidence: str | None = None
    duration_seconds: float | None = None
    size_bytes: int | None = None
    bit_rate: int | None = None
    codec: str | None = None
    sample_rate: int | None = None
    channels: int | None = None
    channel_layout: str | None = None
    container_format: str | None = None
    metadata_title: str | None = None
    metadata_artist: str | None = None
    metadata_album: str | None = None
    metadata_genre: str | None = None
    metadata_comment: str | None = None
    metadata_encoder: str | None = None
    device_or_software: str | None = None


def extract_and_store_audio_metadata(
    connection: Connection,
    meeting_id: str,
    audio_path: Path,
    storage: StoragePaths,
) -> None:
    try:
        raw_metadata = probe_metadata(audio_path)
    except AudioError:
        return

    metadata_dir = storage.artifacts / meeting_id
    metadata_dir.mkdir(parents=True, exist_ok=True)
    raw_metadata_path = metadata_dir / "audio-metadata.ffprobe.json"
    raw_metadata_path.write_text(json.dumps(raw_metadata, indent=2) + "\n")

    normalized = normalize_audio_metadata(raw_metadata, audio_path)
    with connection:
        connection.execute(
            """
            INSERT OR REPLACE INTO audio_metadata(
                id,
                meeting_id,
                raw_metadata_path,
                recorded_at,
                recorded_at_source,
                recorded_at_confidence,
                duration_seconds,
                size_bytes,
                bit_rate,
                codec,
                sample_rate,
                channels,
                channel_layout,
                container_format,
                metadata_title,
                metadata_artist,
                metadata_album,
                metadata_genre,
                metadata_comment,
                metadata_encoder,
                device_or_software
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                meeting_id,
                meeting_id,
                str(raw_metadata_path),
                normalized.recorded_at,
                normalized.recorded_at_source,
                normalized.recorded_at_confidence,
                normalized.duration_seconds,
                normalized.size_bytes,
                normalized.bit_rate,
                normalized.codec,
                normalized.sample_rate,
                normalized.channels,
                normalized.channel_layout,
                normalized.container_format,
                normalized.metadata_title,
                normalized.metadata_artist,
                normalized.metadata_album,
                normalized.metadata_genre,
                normalized.metadata_comment,
                normalized.metadata_encoder,
                normalized.device_or_software,
            ),
        )


def normalize_audio_metadata(raw_metadata: dict, audio_path: Path) -> NormalizedAudioMetadata:
    audio_stream = _first_audio_stream(raw_metadata)
    format_data = raw_metadata.get("format") if isinstance(raw_metadata.get("format"), dict) else {}
    format_tags = _normalized_tags(format_data.get("tags"))
    stream_tags = _normalized_tags(audio_stream.get("tags"))
    tags = {**stream_tags, **format_tags}
    recorded_at, recorded_at_source, recorded_at_confidence = _recorded_at(tags, audio_path)

    return NormalizedAudioMetadata(
        recorded_at=recorded_at,
        recorded_at_source=recorded_at_source,
        recorded_at_confidence=recorded_at_confidence,
        duration_seconds=_optional_float(format_data.get("duration")),
        size_bytes=_optional_int(format_data.get("size")),
        bit_rate=_optional_int(format_data.get("bit_rate") or audio_stream.get("bit_rate")),
        codec=_optional_str(audio_stream.get("codec_name")),
        sample_rate=_optional_int(audio_stream.get("sample_rate")),
        channels=_optional_int(audio_stream.get("channels")),
        channel_layout=_optional_str(audio_stream.get("channel_layout")),
        container_format=_optional_str(format_data.get("format_name")),
        metadata_title=tags.get("title"),
        metadata_artist=tags.get("artist"),
        metadata_album=tags.get("album"),
        metadata_genre=tags.get("genre"),
        metadata_comment=tags.get("comment"),
        metadata_encoder=tags.get("encoder"),
        device_or_software=tags.get("artist") or tags.get("encoder"),
    )


def _first_audio_stream(raw_metadata: dict) -> dict:
    streams = raw_metadata.get("streams")
    if not isinstance(streams, list):
        return {}
    for stream in streams:
        if isinstance(stream, dict) and stream.get("codec_type") == "audio":
            return stream
    return {}


def _normalized_tags(tags: object) -> dict[str, str]:
    if not isinstance(tags, dict):
        return {}
    return {str(key).lower(): str(value).strip() for key, value in tags.items() if str(value).strip()}


def _recorded_at(tags: dict[str, str], audio_path: Path) -> tuple[str | None, str | None, str | None]:
    for key in ("date", "creation_time", "com.apple.quicktime.creationdate"):
        parsed = _parse_datetime(tags.get(key))
        if parsed is not None:
            return parsed, f"metadata.{key}", "medium"

    title = tags.get("title")
    parsed = _parse_philips_title_datetime(title)
    if parsed is not None:
        return parsed, "metadata.title", "high"

    parsed = _parse_recup_filename_datetime(audio_path.name)
    if parsed is not None:
        return parsed, "filename.recup", "medium"

    parsed = _parse_recorder_filename_datetime(audio_path.name)
    if parsed is not None:
        return parsed, "filename.recorder", "medium"

    try:
        mtime = datetime.fromtimestamp(audio_path.stat().st_mtime).replace(microsecond=0)
    except OSError:
        return None, None, None
    return _format_datetime(mtime), "filesystem.mtime", "low"


def _parse_philips_title_datetime(value: str | None) -> str | None:
    if not value:
        return None
    match = re.search(r"(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2}:\d{2})", value)
    if match is None:
        return None
    return _parse_datetime(f"{match.group(1)} {match.group(2)}")


def _parse_recup_filename_datetime(value: str) -> str | None:
    match = re.search(r"DV-(\d{4})-(\d{2})-(\d{2})-(\d{2})(\d{2})(\d{2})", value)
    if match is None:
        return None
    year, month, day, hour, minute, second = match.groups()
    return _parse_datetime(f"{year}-{month}-{day} {hour}:{minute}:{second}")


def _parse_recorder_filename_datetime(value: str) -> str | None:
    match = re.search(r"(\d{2})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})", value)
    if match is None:
        return None
    year, month, day, hour, minute, second = match.groups()
    return _parse_datetime(f"20{year}-{month}-{day} {hour}:{minute}:{second}")


def _parse_datetime(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.strip().replace("Z", "+00:00")
    for fmt in (None, "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            if fmt is None:
                parsed = datetime.fromisoformat(normalized)
            else:
                parsed = datetime.strptime(normalized, fmt)
        except ValueError:
            continue
        return _format_datetime(parsed.replace(tzinfo=None))
    return None


def _format_datetime(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S")


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_int(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _optional_float(value: object) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
