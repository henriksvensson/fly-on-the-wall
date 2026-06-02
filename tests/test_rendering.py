from pathlib import Path

from fly_on_the_wall.db import database
from fly_on_the_wall.rendering import render_diarized_transcript
from fly_on_the_wall.storage import ensure_storage_layout


def test_render_diarized_transcript_outputs_provider_labels(tmp_path: Path) -> None:
    output_path = tmp_path / "transcript.txt"

    with database(tmp_path / "fly.db") as connection:
        _insert_normalized_fixture(connection)
        transcript = render_diarized_transcript(connection, "run-1", output_path)

    assert transcript == "speaker_0 [sv]: Hej\n\nspeaker_1 [sv]: Hallå"
    assert output_path.read_text() == transcript + "\n"


def test_render_diarized_transcript_uses_default_artifact_path(tmp_path: Path) -> None:
    storage = ensure_storage_layout(tmp_path / "storage")

    with database(tmp_path / "fly.db") as connection:
        _insert_normalized_fixture(connection)
        transcript = render_diarized_transcript(connection, "run-1", storage=storage)

    output_path = storage.artifacts / "meeting-1" / "diarized-transcript.txt"
    assert output_path.read_text() == transcript + "\n"


def _insert_normalized_fixture(connection) -> None:
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
        "INSERT INTO local_speakers(id, meeting_id, provider_run_id, label) VALUES (?, ?, ?, ?)",
        ("speaker-id-0", "meeting-1", "run-1", "speaker_0"),
    )
    connection.execute(
        "INSERT INTO local_speakers(id, meeting_id, provider_run_id, label) VALUES (?, ?, ?, ?)",
        ("speaker-id-1", "meeting-1", "run-1", "speaker_1"),
    )
    connection.execute(
        """
        INSERT INTO segments(
            id, meeting_id, provider_run_id, local_speaker_id, sequence, text, language
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        ("segment-1", "meeting-1", "run-1", "speaker-id-0", 0, "Hej", "sv"),
    )
    connection.execute(
        """
        INSERT INTO segments(
            id, meeting_id, provider_run_id, local_speaker_id, sequence, text, language
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        ("segment-2", "meeting-1", "run-1", "speaker-id-1", 1, "Hallå", "sv"),
    )
