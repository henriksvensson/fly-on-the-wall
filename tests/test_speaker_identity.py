from pathlib import Path

from fly_on_the_wall.db import database
from fly_on_the_wall.people import create_person
from fly_on_the_wall.speaker_identity import create_voice_identity_from_speaker
from fly_on_the_wall.storage import ensure_storage_layout


class FakeBackend:
    model_name = "fake-model"

    def embed(self, audio_path: Path) -> list[float]:
        return [1.0, 0.0]


def test_create_voice_identity_from_speaker_creates_sample_and_embeddings(tmp_path: Path, monkeypatch) -> None:
    source_audio_path = tmp_path / "meeting.m4a"
    source_audio_path.write_bytes(b"audio")
    storage = ensure_storage_layout(tmp_path / "storage")

    def fake_extract(input_path: Path, output_path: Path, start: float, end: float) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"clip")
        return output_path

    monkeypatch.setattr("fly_on_the_wall.voice_samples.extract_clip", fake_extract)

    with database(tmp_path / "fly.db") as connection:
        _insert_speaker_fixture(connection, source_audio_path)
        person = create_person(connection, "Person B")
        result = create_voice_identity_from_speaker(
            connection,
            "local-1",
            person.id,
            storage=storage,
            backend=FakeBackend(),
        )
        assignment = connection.execute("SELECT * FROM speaker_assignments").fetchone()
        sample = connection.execute("SELECT * FROM voice_samples").fetchone()
        local_embedding = connection.execute("SELECT * FROM local_speaker_embeddings").fetchone()

    assert result.person_name == "Person B"
    assert result.embedded is True
    assert result.voice_sample.audio_path.read_bytes() == b"clip"
    assert assignment["person_id"] == person.id
    assert sample["source_local_speaker_id"] == "local-1"
    assert sample["embedding_path"] is not None
    assert local_embedding["embedding_path"] is not None


def test_create_voice_identity_from_speaker_can_create_person(tmp_path: Path, monkeypatch) -> None:
    source_audio_path = tmp_path / "meeting.m4a"
    source_audio_path.write_bytes(b"audio")
    storage = ensure_storage_layout(tmp_path / "storage")

    def fake_extract(input_path: Path, output_path: Path, start: float, end: float) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"clip")
        return output_path

    monkeypatch.setattr("fly_on_the_wall.voice_samples.extract_clip", fake_extract)

    with database(tmp_path / "fly.db") as connection:
        _insert_speaker_fixture(connection, source_audio_path)
        result = create_voice_identity_from_speaker(
            connection,
            "local-1",
            "Person B",
            create_missing_person=True,
            storage=storage,
        )
        person = connection.execute("SELECT * FROM people").fetchone()

    assert result.person_name == "Person B"
    assert result.embedded is False
    assert person["display_name"] == "Person B"


def _insert_speaker_fixture(connection, source_audio_path: Path) -> None:
    connection.execute(
        """
        INSERT INTO meetings(id, slug, title, language, imported_audio_path)
        VALUES (?, ?, ?, ?, ?)
        """,
        ("meeting-1", "meeting-1", "Meeting", "sv", str(source_audio_path)),
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
    connection.execute(
        """
        INSERT INTO segments(
            id, meeting_id, provider_run_id, local_speaker_id, sequence, start_time, end_time, text
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("segment-1", "meeting-1", "run-1", "local-1", 0, 1.0, 4.0, "Hej"),
    )
