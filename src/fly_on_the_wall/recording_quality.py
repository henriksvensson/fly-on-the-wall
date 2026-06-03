from __future__ import annotations

import json
import re
from dataclasses import dataclass
from sqlite3 import Connection

from fly_on_the_wall.meetings import Meeting
from fly_on_the_wall.normalization import NormalizedSegment

MIN_DURATION_SECONDS = 3.0
SUSPICIOUS_DURATION_SECONDS = 10.0
SPARSE_DURATION_SECONDS = 120.0
SPARSE_WORDS_PER_SECOND = 0.02
MIN_MEANINGFUL_WORDS = 3

FILLER_WORDS = {
    "ah",
    "eh",
    "ehm",
    "hm",
    "hmm",
    "ja",
    "mm",
    "mmm",
    "nej",
    "ok",
    "okej",
    "uh",
    "um",
    "yes",
    "no",
}
HALLUCINATION_PHRASES = {
    "tack för att du tittade",
    "thanks for watching",
    "thank you for watching",
}


@dataclass(frozen=True)
class RecordingQuality:
    status: str
    reason: str
    details: dict


class RecordingIgnoredError(RuntimeError):
    def __init__(self, meeting: Meeting, quality: RecordingQuality) -> None:
        super().__init__(quality.reason)
        self.meeting = meeting
        self.quality = quality


def assess_before_transcription(
    connection: Connection, meeting: Meeting
) -> RecordingQuality | None:
    duration = _duration_seconds(connection, meeting.id)
    if duration is None:
        return None
    if duration < MIN_DURATION_SECONDS:
        return RecordingQuality(
            "empty",
            "audio_too_short",
            {"duration_seconds": duration, "threshold_seconds": MIN_DURATION_SECONDS},
        )
    if duration < SUSPICIOUS_DURATION_SECONDS:
        return RecordingQuality(
            "suspicious",
            "audio_very_short",
            {"duration_seconds": duration, "threshold_seconds": SUSPICIOUS_DURATION_SECONDS},
        )
    return None


def assess_after_transcription(
    connection: Connection, meeting: Meeting, segments: list[NormalizedSegment]
) -> RecordingQuality:
    duration = _duration_seconds(connection, meeting.id)
    texts = [segment.text for segment in segments]
    words = _words(" ".join(texts))
    meaningful_words = [word for word in words if word not in FILLER_WORDS]
    details = {
        "segment_count": len(segments),
        "word_count": len(words),
        "meaningful_word_count": len(meaningful_words),
        "duration_seconds": duration,
    }

    if not segments:
        return RecordingQuality("empty", "no_transcript_segments", details)
    if words and not meaningful_words:
        return RecordingQuality("empty", "only_filler_words", details)
    if _looks_like_hallucinated_boilerplate(" ".join(words)):
        return RecordingQuality("nonsense", "hallucinated_boilerplate", details)
    if duration is not None and duration >= SPARSE_DURATION_SECONDS:
        density = len(words) / duration
        details["words_per_second"] = density
        if density < SPARSE_WORDS_PER_SECOND:
            return RecordingQuality("nonsense", "very_low_speech_density", details)
    if len(meaningful_words) < MIN_MEANINGFUL_WORDS:
        return RecordingQuality("suspicious", "too_few_meaningful_words", details)
    return RecordingQuality("normal", "passed_quality_checks", details)


def store_recording_quality(
    connection: Connection, meeting_id: str, quality: RecordingQuality
) -> None:
    with connection:
        connection.execute(
            """
            INSERT OR REPLACE INTO recording_quality(
                id, meeting_id, status, reason, details_json, updated_at
            ) VALUES (
                COALESCE((SELECT id FROM recording_quality WHERE meeting_id = ?), ?),
                ?, ?, ?, ?, CURRENT_TIMESTAMP
            )
            """,
            (
                meeting_id,
                meeting_id,
                meeting_id,
                quality.status,
                quality.reason,
                json.dumps(quality.details, sort_keys=True),
            ),
        )


def _duration_seconds(connection: Connection, meeting_id: str) -> float | None:
    row = connection.execute(
        "SELECT duration_seconds FROM audio_metadata WHERE meeting_id = ?", (meeting_id,)
    ).fetchone()
    if row is None or row["duration_seconds"] is None:
        return None
    return float(row["duration_seconds"])


def _words(text: str) -> list[str]:
    return [word.lower() for word in re.findall(r"[\wåäöÅÄÖ]+", text)]


def _looks_like_hallucinated_boilerplate(text: str) -> bool:
    normalized = " ".join(text.lower().split())
    return any(phrase in normalized for phrase in HALLUCINATION_PHRASES)
