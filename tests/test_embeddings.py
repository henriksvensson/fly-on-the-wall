from pathlib import Path

import pytest

from fly_on_the_wall.db import database
from fly_on_the_wall.embeddings import (
    cache_local_speaker_embedding,
    cache_voice_sample_embedding,
    cosine_similarity,
    read_embedding,
)
from fly_on_the_wall.people import create_person
from fly_on_the_wall.storage import ensure_storage_layout
from fly_on_the_wall.voice_samples import create_voice_sample_from_clip


class FakeBackend:
    model_name = "fake-model"

    def embed(self, audio_path: Path) -> list[float]:
        return [1.0, 0.0, 0.0]


def test_cache_voice_sample_embedding_updates_sample(tmp_path: Path) -> None:
    clip_path = tmp_path / "clip.wav"
    clip_path.write_bytes(b"voice")
    storage = ensure_storage_layout(tmp_path / "storage")

    with database(tmp_path / "fly.db") as connection:
        person = create_person(connection, "Person A")
        sample = create_voice_sample_from_clip(connection, person.id, clip_path, storage)
        cached = cache_voice_sample_embedding(connection, sample.id, FakeBackend(), storage)
        row = connection.execute("SELECT * FROM voice_samples WHERE id = ?", (sample.id,)).fetchone()

    assert cached.vector == [1.0, 0.0, 0.0]
    assert read_embedding(cached.path) == [1.0, 0.0, 0.0]
    assert row["embedding_model"] == "fake-model"
    assert row["embedding_path"] == str(cached.path)


def test_cache_local_speaker_embedding_upserts_embedding(tmp_path: Path) -> None:
    audio_path = tmp_path / "speaker.wav"
    audio_path.write_bytes(b"voice")
    storage = ensure_storage_layout(tmp_path / "storage")

    with database(tmp_path / "fly.db") as connection:
        connection.execute(
            "INSERT INTO meetings(id, slug, title, language) VALUES (?, ?, ?, ?)",
            ("meeting-1", "meeting-1", "Meeting", "sv"),
        )
        connection.execute(
            """
            INSERT INTO provider_runs(id, meeting_id, provider, model, raw_response_path, status)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("run-1", "meeting-1", "elevenlabs", "scribe_v2", "raw.json", "done"),
        )
        connection.execute(
            """
            INSERT INTO local_speakers(id, meeting_id, provider_run_id, label)
            VALUES (?, ?, ?, ?)
            """,
            ("local-1", "meeting-1", "run-1", "speaker_0"),
        )
        cached = cache_local_speaker_embedding(connection, "local-1", audio_path, FakeBackend(), storage)
        cached_again = cache_local_speaker_embedding(connection, "local-1", audio_path, FakeBackend(), storage)
        rows = connection.execute("SELECT * FROM local_speaker_embeddings").fetchall()

    assert len(rows) == 1
    assert cached_again.path == cached.path


def test_cosine_similarity() -> None:
    assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) == 1.0
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == 0.0
    with pytest.raises(ValueError, match="same length"):
        cosine_similarity([1.0], [1.0, 2.0])
