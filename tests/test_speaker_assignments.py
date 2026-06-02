from fly_on_the_wall.db import database
from fly_on_the_wall.people import create_person
from fly_on_the_wall.speakers import assign_speaker_to_person, create_person_from_speaker


def test_assign_speaker_to_existing_person_records_correction(tmp_path) -> None:
    with database(tmp_path / "fly.db") as connection:
        _insert_unknown_fixture(connection)
        person = create_person(connection, "Person B")
        assignment = assign_speaker_to_person(connection, "local-1", person.id)
        correction = connection.execute("SELECT * FROM corrections").fetchone()

    assert assignment["name"] == "Person B"
    assert correction["correction_type"] == "speaker_assignment"


def test_create_person_from_speaker_creates_and_assigns(tmp_path) -> None:
    with database(tmp_path / "fly.db") as connection:
        _insert_unknown_fixture(connection)
        assignment = create_person_from_speaker(connection, "local-1", "Person B")
        row = connection.execute("SELECT * FROM speaker_assignments").fetchone()

    assert assignment["name"] == "Person B"
    assert row["status"] == "known"


def _insert_unknown_fixture(connection) -> None:
    connection.execute(
        "INSERT INTO meetings(id, slug, title, language) VALUES (?, ?, ?, ?)",
        ("meeting-1", "intro", "Intro", "sv"),
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
