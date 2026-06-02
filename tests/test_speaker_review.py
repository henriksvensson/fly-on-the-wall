from fly_on_the_wall.db import database
from fly_on_the_wall.speakers import speaker_examples


def test_speaker_examples_returns_segment_examples(tmp_path) -> None:
    with database(tmp_path / "fly.db") as connection:
        _insert_unknown_fixture(connection)
        examples = speaker_examples(connection, "local-1")

    assert examples == [{"text": "Hej", "start_time": None, "end_time": None}]


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
