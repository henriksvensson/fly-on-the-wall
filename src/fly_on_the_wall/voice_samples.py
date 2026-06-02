from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from sqlite3 import Connection
from uuid import uuid4

from fly_on_the_wall.audio import extract_clip
from fly_on_the_wall.storage import StoragePaths, storage_paths


@dataclass(frozen=True)
class VoiceSample:
    id: str
    person_id: str
    audio_path: Path
    source_meeting_id: str | None = None
    source_local_speaker_id: str | None = None
    start_time: float | None = None
    end_time: float | None = None


def create_voice_sample_from_clip(
    connection: Connection,
    person_id: str,
    clip_path: Path,
    storage: StoragePaths | None = None,
) -> VoiceSample:
    if not clip_path.is_file():
        raise FileNotFoundError(f"Voice sample clip does not exist: {clip_path}")

    paths = storage or storage_paths()
    sample_id = str(uuid4())
    stored_path = paths.voice_samples / person_id / f"{sample_id}{clip_path.suffix}"
    stored_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(clip_path, stored_path)

    sample = VoiceSample(id=sample_id, person_id=person_id, audio_path=stored_path)
    _insert_voice_sample(connection, sample)
    return sample


def create_voice_sample_from_span(
    connection: Connection,
    person_id: str,
    source_audio_path: Path,
    source_meeting_id: str,
    source_local_speaker_id: str | None,
    start_time: float,
    end_time: float,
    storage: StoragePaths | None = None,
) -> VoiceSample:
    paths = storage or storage_paths()
    sample_id = str(uuid4())
    stored_path = paths.voice_samples / person_id / f"{sample_id}.wav"
    extract_clip(source_audio_path, stored_path, start_time, end_time)

    sample = VoiceSample(
        id=sample_id,
        person_id=person_id,
        audio_path=stored_path,
        source_meeting_id=source_meeting_id,
        source_local_speaker_id=source_local_speaker_id,
        start_time=start_time,
        end_time=end_time,
    )
    _insert_voice_sample(connection, sample)
    return sample


def list_voice_samples(connection: Connection, person_id: str) -> list[VoiceSample]:
    rows = connection.execute(
        """
        SELECT id,
               person_id,
               audio_path,
               source_meeting_id,
               source_local_speaker_id,
               start_time,
               end_time
        FROM voice_samples
        WHERE person_id = ?
        ORDER BY created_at
        """,
        (person_id,),
    ).fetchall()
    return [
        VoiceSample(
            id=row["id"],
            person_id=row["person_id"],
            audio_path=Path(row["audio_path"]),
            source_meeting_id=row["source_meeting_id"],
            source_local_speaker_id=row["source_local_speaker_id"],
            start_time=row["start_time"],
            end_time=row["end_time"],
        )
        for row in rows
    ]


def _insert_voice_sample(connection: Connection, sample: VoiceSample) -> None:
    with connection:
        connection.execute(
            """
            INSERT INTO voice_samples(
                id,
                person_id,
                source_meeting_id,
                source_local_speaker_id,
                start_time,
                end_time,
                audio_path
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                sample.id,
                sample.person_id,
                sample.source_meeting_id,
                sample.source_local_speaker_id,
                sample.start_time,
                sample.end_time,
                str(sample.audio_path),
            ),
        )
