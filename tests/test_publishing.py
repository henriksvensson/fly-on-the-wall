import json
from pathlib import Path
from sqlite3 import Connection

from fly_on_the_wall.config import AppConfig
from fly_on_the_wall.db import database
from fly_on_the_wall.exporting import export_markdown_transcript
from fly_on_the_wall.processing import process_audio
from fly_on_the_wall.publishing import (
    add_publish_target,
    list_publish_targets,
    publish_meeting,
    remove_publish_target,
)
from fly_on_the_wall.storage import StoragePaths, ensure_storage_layout


def test_publish_target_crud(tmp_path: Path) -> None:
    target_path = tmp_path / "vault" / "Meetings"

    with database(tmp_path / "fly.db") as connection:
        target = add_publish_target(
            connection, "obsidian", target_path, "obsidian", auto_publish=True
        )
        targets = list_publish_targets(connection)
        removed = remove_publish_target(connection, "obsidian")

    assert targets == [target]
    assert target.auto_publish
    assert removed == target


def test_publish_meeting_writes_and_updates_obsidian_note(tmp_path: Path) -> None:
    storage = ensure_storage_layout(tmp_path / "storage")
    target_path = tmp_path / "vault" / "Meetings"

    with database(tmp_path / "fly.db") as connection:
        connection.execute(
            """
            INSERT INTO meetings(id, slug, title, language, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("meeting-1", "intro", "Intro Call", "sv", "2026-06-02 10:09:00"),
        )
        export_markdown_transcript(
            connection,
            "meeting-1",
            "Person B: Hej där alla",
            "# Meeting Analysis\n\n## Summary\n\nUseful discussion.",
            storage,
        )
        add_publish_target(connection, "obsidian", target_path, "obsidian")

        first = publish_meeting(connection, "intro", "obsidian")
        connection.execute(
            "UPDATE meetings SET title = ? WHERE id = ?", ("Renamed Call", "meeting-1")
        )
        export_markdown_transcript(
            connection,
            "meeting-1",
            "Person B: Hej där alla igen",
            "# Meeting Analysis\n\n## Summary\n\nUpdated discussion.",
            storage,
        )
        second = publish_meeting(connection, "intro", "obsidian")
        published_count = connection.execute("SELECT COUNT(*) FROM published_items").fetchone()[0]

    note = first.output_path.read_text()
    assert first.output_path == target_path / "2026-06-02 Intro Call.md"
    assert second.output_path == first.output_path
    assert published_count == 1
    assert "title: Renamed Call" in note
    assert "Updated discussion." in note
    assert "**Person B:** Hej där alla igen" in note
    assert "managed by Fly on the Wall" in note


def test_process_audio_auto_publishes_enabled_targets(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr("fly_on_the_wall.processing.get_api_key", lambda provider: None)
    audio_path = tmp_path / "meeting.m4a"
    audio_path.write_bytes(b"audio")
    storage = ensure_storage_layout(tmp_path / "storage")
    target_path = tmp_path / "vault" / "Meetings"

    def fake_transcribe(
        connection: Connection, meeting_id: str, audio_path: Path, storage: StoragePaths
    ) -> str:
        raw_path = storage.artifacts / meeting_id / "raw.json"
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_text(
            json.dumps(
                {
                    "language_code": "sv",
                    "words": [
                        {"speaker_id": "speaker_0", "text": "Hej ", "start": 0, "end": 0.2},
                        {"speaker_id": "speaker_0", "text": "viktigt ", "start": 0.2, "end": 0.4},
                        {"speaker_id": "speaker_0", "text": "möte", "start": 0.4, "end": 0.6},
                    ],
                }
            )
        )
        connection.execute(
            """
            INSERT INTO provider_runs(id, meeting_id, provider, model, raw_response_path, status)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("run-1", meeting_id, "elevenlabs", "scribe_v2", str(raw_path), "done"),
        )
        return "run-1"

    with database(tmp_path / "fly.db") as connection:
        add_publish_target(connection, "obsidian", target_path, "obsidian", auto_publish=True)
        result = process_audio(
            connection,
            audio_path,
            "Manual Title",
            AppConfig(cleanup_mode="deterministic"),
            storage,
            transcribe_fn=fake_transcribe,
        )
        published = connection.execute("SELECT * FROM published_items").fetchone()

    assert published is not None
    output_path = Path(published["output_path"])
    assert output_path.exists()
    assert result.meeting.title == "Manual Title"
    assert "# Manual Title" in output_path.read_text()
