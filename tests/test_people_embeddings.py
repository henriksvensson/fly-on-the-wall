from pathlib import Path

from fly_on_the_wall.db import database
from fly_on_the_wall.people import create_person
from fly_on_the_wall.people_embeddings import (
    backfill_people_embeddings,
    people_embedding_status,
)
from fly_on_the_wall.storage import ensure_storage_layout
from fly_on_the_wall.voice_samples import create_voice_sample_from_clip


class FakeBackend:
    model_name = "fake-model"

    def embed(self, audio_path: Path) -> list[float]:
        return [1.0, 0.0, 0.0]


def test_people_embedding_status_counts_voice_samples(tmp_path: Path) -> None:
    clip_path = tmp_path / "clip.wav"
    clip_path.write_bytes(b"voice")
    storage = ensure_storage_layout(tmp_path / "storage")

    with database(tmp_path / "fly.db") as connection:
        person = create_person(connection, "Person B")
        sample = create_voice_sample_from_clip(connection, person.id, clip_path, storage)
        connection.execute(
            "UPDATE voice_samples SET embedding_path = ? WHERE id = ?",
            ("embedding.json", sample.id),
        )

        status = people_embedding_status(connection)

    assert status.people == 1
    assert status.voice_samples == 1
    assert status.embedded_voice_samples == 1
    assert status.missing_voice_sample_embeddings == 0


def test_backfill_people_embeddings_embeds_missing_voice_samples(
    tmp_path: Path,
) -> None:
    clip_path = tmp_path / "clip.wav"
    clip_path.write_bytes(b"voice")
    storage = ensure_storage_layout(tmp_path / "storage")

    with database(tmp_path / "fly.db") as connection:
        person = create_person(connection, "Person B")
        sample = create_voice_sample_from_clip(connection, person.id, clip_path, storage)

        result = backfill_people_embeddings(connection, storage, FakeBackend())
        row = connection.execute(
            "SELECT embedding_model, embedding_path FROM voice_samples WHERE id = ?",
            (sample.id,),
        ).fetchone()

    assert result.embedded == 1
    assert result.failed == 0
    assert row["embedding_model"] == "fake-model"
    assert Path(row["embedding_path"]).is_file()
