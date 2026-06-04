from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from sqlite3 import Connection
from typing import Any
from uuid import uuid4


@dataclass(frozen=True)
class NormalizedSegment:
    id: str
    sequence: int
    speaker_label: str
    text: str
    start_time: float | None
    end_time: float | None
    language: str | None


def normalize_provider_run(connection: Connection, provider_run_id: str) -> list[NormalizedSegment]:
    provider_run = connection.execute(
        "SELECT * FROM provider_runs WHERE id = ?", (provider_run_id,)
    ).fetchone()
    if provider_run is None:
        raise ValueError(f"Provider run does not exist: {provider_run_id}")

    raw_response_path = Path(provider_run["raw_response_path"])
    response = json.loads(raw_response_path.read_text())
    segments = normalize_elevenlabs_response(response)

    with connection:
        connection.execute("DELETE FROM segments WHERE provider_run_id = ?", (provider_run_id,))
        for segment in segments:
            local_speaker_id = _ensure_local_speaker(
                connection,
                provider_run["meeting_id"],
                provider_run_id,
                segment.speaker_label,
            )
            connection.execute(
                """
                INSERT INTO segments(
                    id,
                    meeting_id,
                    provider_run_id,
                    local_speaker_id,
                    sequence,
                    start_time,
                    end_time,
                    text,
                    language,
                    source_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    segment.id,
                    provider_run["meeting_id"],
                    provider_run_id,
                    local_speaker_id,
                    segment.sequence,
                    segment.start_time,
                    segment.end_time,
                    segment.text,
                    segment.language,
                    json.dumps({"speaker_label": segment.speaker_label}, ensure_ascii=False),
                ),
            )

    return segments


def normalize_elevenlabs_response(response: dict[str, Any]) -> list[NormalizedSegment]:
    normalized: list[NormalizedSegment] = []
    sequence = 0
    for transcript in _iter_transcripts(response):
        for speaker_label, words in _speaker_word_groups(transcript.get("words", [])):
            segment = _build_segment(
                sequence, speaker_label, words, transcript.get("language_code")
            )
            if segment is None:
                continue
            normalized.append(segment)
            sequence += 1
    return normalized


def _speaker_word_groups(words: list[dict[str, Any]]) -> list[tuple[str, list[dict[str, Any]]]]:
    groups: list[tuple[str, list[dict[str, Any]]]] = []
    current_speaker: str | None = None
    current_words: list[dict[str, Any]] = []

    for word in words:
        if word.get("type") == "audio_event":
            continue
        speaker = word.get("speaker_id") or "Unknown"
        if current_speaker is not None and speaker != current_speaker:
            groups.append((current_speaker, current_words))
            current_words = []
        current_speaker = speaker
        current_words.append(word)

    if current_speaker is not None:
        groups.append((current_speaker, current_words))
    return groups


def _build_segment(
    sequence: int,
    speaker_label: str | None,
    words: list[dict[str, Any]],
    language: str | None,
) -> NormalizedSegment | None:
    if not words:
        return None
    text = "".join(str(word.get("text", "")) for word in words).strip()
    if not text:
        return None
    return NormalizedSegment(
        id=str(uuid4()),
        sequence=sequence,
        speaker_label=speaker_label or "Unknown",
        text=text,
        start_time=_first_number(words, "start"),
        end_time=_last_number(words, "end"),
        language=language,
    )


def _iter_transcripts(response: dict[str, Any]) -> list[dict[str, Any]]:
    transcripts = response.get("transcripts")
    if isinstance(transcripts, list):
        return [transcript for transcript in transcripts if isinstance(transcript, dict)]
    return [response]


def _ensure_local_speaker(
    connection: Connection, meeting_id: str, provider_run_id: str, label: str
) -> str:
    row = connection.execute(
        "SELECT id FROM local_speakers WHERE provider_run_id = ? AND label = ?",
        (provider_run_id, label),
    ).fetchone()
    if row is not None:
        return row["id"]

    local_speaker_id = str(uuid4())
    connection.execute(
        """
        INSERT INTO local_speakers(id, meeting_id, provider_run_id, label)
        VALUES (?, ?, ?, ?)
        """,
        (local_speaker_id, meeting_id, provider_run_id, label),
    )
    return local_speaker_id


def _first_number(words: list[dict[str, Any]], key: str) -> float | None:
    for word in words:
        value = word.get(key)
        if isinstance(value, int | float):
            return float(value)
    return None


def _last_number(words: list[dict[str, Any]], key: str) -> float | None:
    for word in reversed(words):
        value = word.get(key)
        if isinstance(value, int | float):
            return float(value)
    return None
