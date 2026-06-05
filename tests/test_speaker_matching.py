import json
from pathlib import Path

from fly_on_the_wall.config import ConfidenceThresholds
from fly_on_the_wall.db import database
from fly_on_the_wall.speaker_matching import match_local_speakers


def test_match_local_speakers_assigns_best_person(tmp_path: Path) -> None:
    with database(tmp_path / "fly.db") as connection:
        _insert_matching_fixture(connection, tmp_path)
        matches = match_local_speakers(
            connection,
            "run-1",
            ConfidenceThresholds(named=0.9, uncertain=0.5),
        )
        row = connection.execute("SELECT * FROM speaker_assignments").fetchone()

    assert len(matches) == 1
    assert matches[0].person_id == "person-1"
    assert matches[0].status == "known"
    assert row["person_id"] == "person-1"
    assert row["status"] == "known"


def test_match_local_speakers_marks_unknown_without_embeddings(tmp_path: Path) -> None:
    with database(tmp_path / "fly.db") as connection:
        _insert_base_local_speaker(connection)
        matches = match_local_speakers(connection, "run-1")

    assert matches[0].status == "unknown"
    assert matches[0].person_id is None


def test_match_local_speakers_preserves_user_corrections(tmp_path: Path) -> None:
    with database(tmp_path / "fly.db") as connection:
        _insert_matching_fixture(connection, tmp_path)
        connection.execute(
            """
            INSERT INTO speaker_assignments(id, local_speaker_id, person_id, status, evidence_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                "assignment-1",
                "local-1",
                "person-2",
                "known",
                json.dumps({"method": "user_correction"}),
            ),
        )
        match_local_speakers(connection, "run-1", ConfidenceThresholds(named=0.9, uncertain=0.5))
        row = connection.execute("SELECT * FROM speaker_assignments").fetchone()

    assert row["person_id"] == "person-2"
    assert json.loads(row["evidence_json"])["method"] == "user_correction"


def _insert_matching_fixture(connection, tmp_path: Path) -> None:
    _insert_base_local_speaker(connection)
    local_embedding = tmp_path / "local.json"
    person_a_embedding = tmp_path / "person_a.json"
    bob_embedding = tmp_path / "bob.json"
    local_embedding.write_text(json.dumps({"vector": [1.0, 0.0]}))
    person_a_embedding.write_text(json.dumps({"vector": [1.0, 0.0]}))
    bob_embedding.write_text(json.dumps({"vector": [0.0, 1.0]}))
    connection.execute("INSERT INTO people(id, display_name) VALUES (?, ?)", ("person-1", "Person A"))
    connection.execute("INSERT INTO people(id, display_name) VALUES (?, ?)", ("person-2", "Bob"))
    connection.execute(
        """
        INSERT INTO voice_samples(id, person_id, audio_path, embedding_model, embedding_path)
        VALUES (?, ?, ?, ?, ?)
        """,
        ("voice-1", "person-1", "person_a.wav", "fake", str(person_a_embedding)),
    )
    connection.execute(
        """
        INSERT INTO voice_samples(id, person_id, audio_path, embedding_model, embedding_path)
        VALUES (?, ?, ?, ?, ?)
        """,
        ("voice-2", "person-2", "bob.wav", "fake", str(bob_embedding)),
    )
    connection.execute(
        """
        INSERT INTO local_speaker_embeddings(
            id, local_speaker_id, audio_path, embedding_model, embedding_path
        ) VALUES (?, ?, ?, ?, ?)
        """,
        ("embedding-1", "local-1", "local.wav", "fake", str(local_embedding)),
    )


def _insert_base_local_speaker(connection) -> None:
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
