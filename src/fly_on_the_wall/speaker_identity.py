from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from sqlite3 import Connection

from fly_on_the_wall.embeddings import (
    EmbeddingBackend,
    PyannoteEmbeddingBackend,
    cache_local_speaker_embedding,
    cache_voice_sample_embedding,
)
from fly_on_the_wall.people import create_person, get_person
from fly_on_the_wall.speaker_matching import SpeakerMatch, match_local_speakers
from fly_on_the_wall.speakers import assign_speaker_to_person, mark_speaker_unknown
from fly_on_the_wall.storage import StoragePaths, storage_paths
from fly_on_the_wall.voice_samples import VoiceSample, create_voice_sample_from_span


@dataclass(frozen=True)
class SpeakerClip:
    local_speaker_id: str
    meeting_id: str
    source_audio_path: Path
    start_time: float
    end_time: float


@dataclass(frozen=True)
class VoiceIdentityResult:
    local_speaker_id: str
    person_id: str
    person_name: str
    voice_sample: VoiceSample
    embedded: bool


def create_voice_identity_from_speaker(
    connection: Connection,
    local_speaker_id: str,
    person_id_or_name: str,
    create_missing_person: bool = False,
    storage: StoragePaths | None = None,
    backend: EmbeddingBackend | None = None,
) -> VoiceIdentityResult:
    person = get_person(connection, person_id_or_name)
    if person is None and create_missing_person:
        person = create_person(connection, person_id_or_name)
    if person is None:
        raise ValueError(f"Person not found: {person_id_or_name}")

    clip = representative_speaker_clip(connection, local_speaker_id)
    if clip is None:
        raise ValueError(f"Local speaker has no timestamped audio: {local_speaker_id}")

    paths = storage or storage_paths()
    sample = create_voice_sample_from_span(
        connection,
        person.id,
        clip.source_audio_path,
        clip.meeting_id,
        local_speaker_id,
        clip.start_time,
        clip.end_time,
        paths,
    )
    assign_speaker_to_person(connection, local_speaker_id, person.id)

    embedded = False
    if backend is not None:
        cache_voice_sample_embedding(connection, sample.id, backend, paths)
        cache_local_speaker_embedding(
            connection, local_speaker_id, sample.audio_path, backend, paths
        )
        embedded = True

    return VoiceIdentityResult(
        local_speaker_id=local_speaker_id,
        person_id=person.id,
        person_name=person.display_name,
        voice_sample=sample,
        embedded=embedded,
    )


def prepare_speaker_review_clip(
    connection: Connection,
    local_speaker_id: str,
    storage: StoragePaths | None = None,
) -> Path | None:
    clip = representative_speaker_clip(connection, local_speaker_id)
    if clip is None:
        return None

    paths = storage or storage_paths()
    output_path = paths.artifacts / clip.meeting_id / "review-clips" / f"{local_speaker_id}.wav"
    from fly_on_the_wall.audio import extract_clip

    return extract_clip(clip.source_audio_path, output_path, clip.start_time, clip.end_time)


def cache_provider_run_speaker_embeddings(
    connection: Connection,
    provider_run_id: str,
    backend: EmbeddingBackend,
    storage: StoragePaths | None = None,
) -> int:
    paths = storage or storage_paths()
    rows = connection.execute(
        "SELECT id FROM local_speakers WHERE provider_run_id = ? ORDER BY label",
        (provider_run_id,),
    ).fetchall()
    count = 0
    for row in rows:
        review_clip = prepare_speaker_review_clip(connection, row["id"], paths)
        if review_clip is None:
            continue
        cache_local_speaker_embedding(connection, row["id"], review_clip, backend, paths)
        count += 1
    return count


def match_provider_run_speakers(
    connection: Connection,
    provider_run_id: str,
    backend: EmbeddingBackend | None = None,
    storage: StoragePaths | None = None,
) -> list[SpeakerMatch]:
    if backend is None and not _has_voice_sample_embeddings(connection):
        return match_local_speakers(connection, provider_run_id)

    resolved_backend = backend or PyannoteEmbeddingBackend()
    cache_provider_run_speaker_embeddings(connection, provider_run_id, resolved_backend, storage)
    return match_local_speakers(connection, provider_run_id)


def _has_voice_sample_embeddings(connection: Connection) -> bool:
    return (
        connection.execute(
            "SELECT 1 FROM voice_samples WHERE embedding_path IS NOT NULL LIMIT 1"
        ).fetchone()
        is not None
    )


def representative_speaker_clip(
    connection: Connection,
    local_speaker_id: str,
) -> SpeakerClip | None:
    row = connection.execute(
        """
        SELECT local_speakers.meeting_id,
               meetings.imported_audio_path,
               segments.start_time,
               segments.end_time
        FROM segments
        JOIN local_speakers ON local_speakers.id = segments.local_speaker_id
        JOIN meetings ON meetings.id = local_speakers.meeting_id
        WHERE segments.local_speaker_id = ?
          AND segments.start_time IS NOT NULL
          AND segments.end_time IS NOT NULL
          AND meetings.imported_audio_path IS NOT NULL
        ORDER BY (segments.end_time - segments.start_time) DESC, segments.sequence
        LIMIT 1
        """,
        (local_speaker_id,),
    ).fetchone()
    if row is None:
        return None

    return SpeakerClip(
        local_speaker_id=local_speaker_id,
        meeting_id=row["meeting_id"],
        source_audio_path=Path(row["imported_audio_path"]),
        start_time=float(row["start_time"]),
        end_time=float(row["end_time"]),
    )


def mark_unknown(connection: Connection, local_speaker_id: str) -> None:
    mark_speaker_unknown(connection, local_speaker_id)
