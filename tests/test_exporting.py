import json
from pathlib import Path

from fly_on_the_wall.db import database
from fly_on_the_wall.exporting import export_markdown_transcript
from fly_on_the_wall.storage import ensure_storage_layout


def test_export_markdown_transcript_writes_immutable_snapshot(tmp_path: Path) -> None:
    storage = ensure_storage_layout(tmp_path / "storage")

    with database(tmp_path / "fly.db") as connection:
        connection.execute(
            "INSERT INTO meetings(id, slug, title, language) VALUES (?, ?, ?, ?)",
            ("meeting-1", "intro-call", "Intro Call", "sv"),
        )
        first = export_markdown_transcript(connection, "meeting-1", "Person B: Hej", storage)
        second = export_markdown_transcript(connection, "meeting-1", "Person B: Hej", storage)
        rows = connection.execute("SELECT * FROM exports ORDER BY created_at").fetchall()

    assert first.output_dir != second.output_dir
    assert first.transcript_path.read_text() == "# Intro Call\n\n## Transcript\n\nPerson B: Hej\n"
    assert json.loads(first.manifest_path.read_text())["meeting_id"] == "meeting-1"
    assert len(rows) == 2


def test_export_markdown_transcript_rejects_missing_meeting(tmp_path: Path) -> None:
    with database(tmp_path / "fly.db") as connection:
        try:
            export_markdown_transcript(connection, "missing", "Person B: Hej")
        except ValueError as exc:
            assert "Meeting does not exist" in str(exc)
        else:
            raise AssertionError("Expected ValueError")
