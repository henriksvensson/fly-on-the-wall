from fly_on_the_wall.db import database
from fly_on_the_wall.speakers import list_unknown_speakers, mark_speaker_ignored


def test_list_unknown_speakers_returns_unassigned_local_speakers(tmp_path) -> None:
    with database(tmp_path / "fly.db") as connection:
        _insert_unknown_fixture(connection)
        unknown = list_unknown_speakers(connection, "intro")

    assert len(unknown) == 1
    assert unknown[0]["id"] == "local-1"
    assert unknown[0]["segment_count"] == 1


def test_list_unknown_speakers_excludes_ignored_local_speakers(tmp_path) -> None:
    with database(tmp_path / "fly.db") as connection:
        _insert_unknown_fixture(connection)
        mark_speaker_ignored(connection, "local-1")

        unknown = list_unknown_speakers(connection, "intro")
        assignment = connection.execute("SELECT status FROM speaker_assignments").fetchone()

    assert unknown == []
    assert assignment["status"] == "ignored"


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
    connection.execute(
        """
        INSERT INTO segments(id, meeting_id, provider_run_id, local_speaker_id, sequence, text)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        ("segment-1", "meeting-1", "run-1", "local-1", 0, "Hej"),
    )
