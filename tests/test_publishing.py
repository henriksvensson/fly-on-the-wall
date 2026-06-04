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
    publish_all_meetings,
    publish_meeting,
    remove_publish_target,
)
from fly_on_the_wall.storage import StoragePaths, ensure_storage_layout


def test_publish_target_crud(tmp_path: Path) -> None:
    target_path = tmp_path / "vault" / "Meetings"

    with database(tmp_path / "fly.db") as connection:
        target = add_publish_target(connection, "obsidian", target_path, "obsidian", auto_publish=True)
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
        connection.execute("UPDATE meetings SET title = ? WHERE id = ?", ("Renamed Call", "meeting-1"))
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


def test_process_audio_auto_publishes_enabled_targets(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("fly_on_the_wall.processing.get_api_key", lambda provider: None)
    audio_path = tmp_path / "meeting.m4a"
    audio_path.write_bytes(b"audio")
    storage = ensure_storage_layout(tmp_path / "storage")
    target_path = tmp_path / "vault" / "Meetings"

    def fake_transcribe(connection: Connection, meeting_id: str, audio_path: Path, storage: StoragePaths) -> str:
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


def test_publish_all_meetings_publishes_every_exported_meeting(tmp_path: Path) -> None:
    storage = ensure_storage_layout(tmp_path / "storage")
    target_path = tmp_path / "vault" / "Meetings"

    with database(tmp_path / "fly.db") as connection:
        for index in range(2):
            meeting_id = f"meeting-{index}"
            connection.execute(
                """
                INSERT INTO meetings(id, slug, title, language, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    meeting_id,
                    f"meeting-{index}",
                    f"Meeting {index}",
                    "sv",
                    f"2026-06-0{index + 1} 10:00:00",
                ),
            )
            export_markdown_transcript(
                connection,
                meeting_id,
                "Person B: Hej där alla",
                "# Meeting Analysis\n\n## Summary\n\nUseful discussion.",
                storage,
            )
        add_publish_target(connection, "obsidian", target_path, "obsidian")

        results = publish_all_meetings(connection, "obsidian")

    assert len(results) == 2
    assert (target_path / "2026-06-01 Meeting 0.md").exists()
    assert (target_path / "2026-06-02 Meeting 1.md").exists()


def test_publish_all_meetings_can_skip_already_published(tmp_path: Path) -> None:
    storage = ensure_storage_layout(tmp_path / "storage")
    target_path = tmp_path / "vault" / "Meetings"

    with database(tmp_path / "fly.db") as connection:
        connection.execute(
            """
            INSERT INTO meetings(id, slug, title, language, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("meeting-1", "meeting", "Meeting", "sv", "2026-06-01 10:00:00"),
        )
        export_markdown_transcript(
            connection,
            "meeting-1",
            "Person B: Hej där alla",
            "# Meeting Analysis\n\n## Summary\n\nUseful discussion.",
            storage,
        )
        add_publish_target(connection, "obsidian", target_path, "obsidian")
        first = publish_all_meetings(connection, "obsidian", only_unpublished=True)
        second = publish_all_meetings(connection, "obsidian", only_unpublished=True)

    assert len(first) == 1
    assert second == []


def test_publish_meeting_handles_legacy_manifest_without_analysis_path(tmp_path: Path) -> None:
    target_path = tmp_path / "vault" / "Meetings"
    export_dir = tmp_path / "exports" / "intro" / "snapshot"
    export_dir.mkdir(parents=True)
    transcript_path = export_dir / "transcript.md"
    manifest_path = export_dir / "manifest.json"
    transcript_path.write_text("# Intro Call\n\nDate: 2026-06-02\nTime: 10:09:00\n\n## Transcript\n\n**Person B:** Hej\n")
    manifest_path.write_text(
        json.dumps(
            {
                "id": "legacy-export",
                "meeting_id": "meeting-1",
                "format": "markdown",
                "transcript_path": str(transcript_path),
            }
        )
    )

    with database(tmp_path / "fly.db") as connection:
        connection.execute(
            """
            INSERT INTO meetings(id, slug, title, language, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("meeting-1", "intro", "Intro Call", "sv", "2026-06-02 10:09:00"),
        )
        connection.execute(
            """
            INSERT INTO exports(id, meeting_id, format, output_dir, manifest_path)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("export-1", "meeting-1", "markdown", str(export_dir), str(manifest_path)),
        )
        add_publish_target(connection, "obsidian", target_path, "obsidian")

        result = publish_meeting(connection, "intro", "obsidian")

    note = result.output_path.read_text()
    assert "No analysis export found" in note
    assert "**Person B:** Hej" in note
