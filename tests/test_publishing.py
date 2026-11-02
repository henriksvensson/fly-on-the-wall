import json
from pathlib import Path
from sqlite3 import Connection

import pytest

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
        connection.execute(
            """
            INSERT INTO provider_runs(id, meeting_id, provider, model, status)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("run-1", "meeting-1", "elevenlabs", "scribe_v2", "done"),
        )
        connection.execute(
            """
            INSERT INTO local_speakers(id, meeting_id, provider_run_id, label)
            VALUES (?, ?, ?, ?)
            """,
            ("speaker-1", "meeting-1", "run-1", "speaker_0"),
        )
        connection.execute("INSERT INTO people(id, display_name) VALUES (?, ?)", ("person-1", "Person A"))
        connection.execute(
            """
            INSERT INTO speaker_assignments(id, local_speaker_id, person_id, status)
            VALUES (?, ?, ?, ?)
            """,
            ("assignment-1", "speaker-1", "person-1", "known"),
        )
        export_markdown_transcript(
            connection,
            "meeting-1",
            "Person A: Hej där alla",
            "# Meeting Analysis\n\n## Summary\n\nUseful discussion.",
            storage,
        )
        add_publish_target(connection, "obsidian", target_path, "obsidian")

        first = publish_meeting(connection, "intro", "obsidian")
        connection.execute("UPDATE meetings SET title = ? WHERE id = ?", ("Renamed Call", "meeting-1"))
        export_markdown_transcript(
            connection,
            "meeting-1",
            "Person A: Hej där alla igen",
            "# Meeting Analysis\n\n## Summary\n\nUpdated discussion.",
            storage,
        )
        second = publish_meeting(connection, "intro", "obsidian")
        published_count = connection.execute("SELECT COUNT(*) FROM published_items").fetchone()[0]

    note = second.output_path.read_text()
    assert first.output_path == target_path / "2026-06-02 10-09-00 Intro Call.md"
    assert second.output_path == target_path / "2026-06-02 10-09-00 Renamed Call.md"
    assert not first.output_path.exists()
    assert published_count == 1
    assert "title: Renamed Call" in note
    assert 'participants:\n  - "[[People/Person A]]"' in note
    assert "Updated discussion." in note
    assert "## Manuscript" in note
    assert "## Transcript" not in note
    assert "**Person A:** Hej där alla igen" in note
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
                "Person A: Hej där alla",
                "# Meeting Analysis\n\n## Summary\n\nUseful discussion.",
                storage,
            )
        add_publish_target(connection, "obsidian", target_path, "obsidian")

        results = publish_all_meetings(connection, "obsidian")

    assert len(results) == 2
    assert (target_path / "2026-06-01 10-00-00 Meeting 0.md").exists()
    assert (target_path / "2026-06-02 10-00-00 Meeting 1.md").exists()


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
            "Person A: Hej där alla",
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
    transcript_path.write_text(
        "# Intro Call\n\nDate: 2026-06-02\nTime: 10:09:00\n\n## Transcript\n\n**Person A:** Hej\n"
    )
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
    assert "## Manuscript" in note
    assert "## Transcript" not in note
    assert "**Person A:** Hej" in note


@pytest.mark.parametrize(
    ("recorded_at", "confidence", "expected_timestamp"),
    [
        ("2026-06-01 23:04:05", "high", "2026-06-01 23-04-05"),
        ("2026-06-01 03:04:05", "medium", "2026-06-01 03-04-05"),
        ("2026-06-01T23:04:05+02:00", "high", "2026-06-01 23-04-05"),
        ("2026-06-01 23:04:05", "low", "2026-06-02 10-09-00"),
        (None, None, "2026-06-02 10-09-00"),
    ],
)
def test_publish_filename_uses_confident_recording_timestamp(
    tmp_path: Path, recorded_at: str | None, confidence: str | None, expected_timestamp: str
) -> None:
    storage = ensure_storage_layout(tmp_path / "storage")
    with database(tmp_path / "fly.db") as connection:
        _export_test_meeting(connection, storage)
        connection.execute(
            "INSERT INTO audio_metadata(id, meeting_id, recorded_at, recorded_at_confidence) VALUES (?, ?, ?, ?)",
            ("metadata-1", "meeting-1", recorded_at, confidence),
        )
        add_publish_target(connection, "obsidian", tmp_path / "vault", "obsidian")

        result = publish_meeting(connection, "meeting-1", "obsidian")

    assert result.output_path.name == f"{expected_timestamp} Intro Call.md"
    assert f"Time: {expected_timestamp.split()[1].replace('-', ':')}" in result.output_path.read_text()


def test_publish_filenames_sort_chronologically(tmp_path: Path) -> None:
    storage = ensure_storage_layout(tmp_path / "storage")
    with database(tmp_path / "fly.db") as connection:
        add_publish_target(connection, "obsidian", tmp_path / "vault", "obsidian")
        for index, time in enumerate(["23:59:59", "03:04:05", "12:00:00"]):
            meeting_id = f"meeting-{index}"
            _export_test_meeting(connection, storage, meeting_id)
            connection.execute("UPDATE meetings SET created_at = ? WHERE id = ?", (f"2026-06-02 {time}", meeting_id))

        results = publish_all_meetings(connection, "obsidian")

    assert sorted(result.output_path.name for result in results) == [
        "2026-06-02 03-04-05 Intro Call.md",
        "2026-06-02 12-00-00 Intro Call.md",
        "2026-06-02 23-59-59 Intro Call.md",
    ]


def test_publish_avoids_collisions_and_reuses_its_own_suffixed_path(tmp_path: Path) -> None:
    storage = ensure_storage_layout(tmp_path / "storage")
    with database(tmp_path / "fly.db") as connection:
        add_publish_target(connection, "obsidian", tmp_path / "vault", "obsidian")
        for index in range(1, 4):
            _export_test_meeting(connection, storage, f"meeting-{index}")

        results = [publish_meeting(connection, f"meeting-{index}", "obsidian") for index in range(1, 4)]
        repeated = publish_meeting(connection, "meeting-2", "obsidian")

    assert [result.output_path.name for result in results] == [
        "2026-06-02 10-09-00 Intro Call.md",
        "2026-06-02 10-09-00 Intro Call (2).md",
        "2026-06-02 10-09-00 Intro Call (3).md",
    ]
    assert repeated.output_path == results[1].output_path
    for index, result in enumerate(results, start=1):
        assert f"meeting_id: meeting-{index}" in result.output_path.read_text()


def test_publish_preserves_untracked_files_and_skips_dangling_symlinks(tmp_path: Path) -> None:
    storage = ensure_storage_layout(tmp_path / "storage")
    target_path = tmp_path / "vault"
    target_path.mkdir()
    occupied_path = target_path / "2026-06-02 10-09-00 Intro Call.md"
    occupied_path.write_text("My personal note")
    symlink_path = target_path / "2026-06-02 10-09-00 Intro Call (2).md"
    symlink_target = tmp_path / "do-not-create.md"
    symlink_path.symlink_to(symlink_target)
    with database(tmp_path / "fly.db") as connection:
        _export_test_meeting(connection, storage)
        add_publish_target(connection, "obsidian", target_path, "obsidian")

        result = publish_meeting(connection, "meeting-1", "obsidian")

    assert result.output_path.name == "2026-06-02 10-09-00 Intro Call (3).md"
    assert occupied_path.read_text() == "My personal note"
    assert symlink_path.is_symlink()
    assert not symlink_target.exists()


def test_publish_reserves_missing_notes_across_overlapping_targets(tmp_path: Path) -> None:
    storage = ensure_storage_layout(tmp_path / "storage")
    target_path = tmp_path / "vault"
    with database(tmp_path / "fly.db") as connection:
        _export_test_meeting(connection, storage, "meeting-1")
        _export_test_meeting(connection, storage, "meeting-2")
        add_publish_target(connection, "obsidian", target_path, "first-target")
        add_publish_target(connection, "obsidian", target_path, "second-target")
        first = publish_meeting(connection, "meeting-1", "first-target")
        first.output_path.unlink()

        second = publish_meeting(connection, "meeting-2", "second-target")
        repeated = publish_meeting(connection, "meeting-1", "first-target")

    assert second.output_path.name == "2026-06-02 10-09-00 Intro Call (2).md"
    assert repeated.output_path == first.output_path
    assert "meeting_id: meeting-2" in second.output_path.read_text()
    assert "meeting_id: meeting-1" in repeated.output_path.read_text()


def test_republish_migrates_legacy_filename_and_removes_manually_edited_old_note(tmp_path: Path) -> None:
    storage = ensure_storage_layout(tmp_path / "storage")
    with database(tmp_path / "fly.db") as connection:
        _export_test_meeting(connection, storage)
        add_publish_target(connection, "obsidian", tmp_path / "vault", "obsidian")
        first = publish_meeting(connection, "meeting-1", "obsidian")
        legacy_path = first.output_path.with_name("2026-06-02 Intro Call.md")
        first.output_path.rename(legacy_path)
        legacy_path.write_text("Manual edits to managed output")
        connection.execute("UPDATE published_items SET output_path = ?", (str(legacy_path),))

        result = publish_meeting(connection, "meeting-1", "obsidian")
        tracked_path = connection.execute("SELECT output_path FROM published_items").fetchone()[0]

    assert result.output_path == first.output_path
    assert tracked_path == str(result.output_path)
    assert "meeting_id: meeting-1" in result.output_path.read_text()
    assert not legacy_path.exists()


def test_republish_follows_timestamp_changes_without_overwriting_destination(tmp_path: Path) -> None:
    storage = ensure_storage_layout(tmp_path / "storage")
    target_path = tmp_path / "vault"
    with database(tmp_path / "fly.db") as connection:
        _export_test_meeting(connection, storage)
        add_publish_target(connection, "obsidian", target_path, "obsidian")
        first = publish_meeting(connection, "meeting-1", "obsidian")
        connection.execute(
            "INSERT INTO audio_metadata(id, meeting_id, recorded_at, recorded_at_confidence) VALUES (?, ?, ?, ?)",
            ("metadata-1", "meeting-1", "2026-06-01 23:04:05", "high"),
        )
        occupied_path = target_path / "2026-06-01 23-04-05 Intro Call.md"
        occupied_path.write_text("Unrelated note")

        result = publish_meeting(connection, "meeting-1", "obsidian")

    assert result.output_path.name == "2026-06-01 23-04-05 Intro Call (2).md"
    assert "Time: 23:04:05" in result.output_path.read_text()
    assert not first.output_path.exists()
    assert occupied_path.read_text() == "Unrelated note"


def test_republish_does_not_remove_old_path_shared_by_legacy_publications(tmp_path: Path) -> None:
    storage = ensure_storage_layout(tmp_path / "storage")
    with database(tmp_path / "fly.db") as connection:
        add_publish_target(connection, "obsidian", tmp_path / "vault", "obsidian")
        _export_test_meeting(connection, storage, "meeting-1")
        _export_test_meeting(connection, storage, "meeting-2")
        first = publish_meeting(connection, "meeting-1", "obsidian")
        second = publish_meeting(connection, "meeting-2", "obsidian")
        second.output_path.unlink()
        connection.execute(
            "UPDATE published_items SET output_path = ? WHERE meeting_id = ?",
            (str(first.output_path), "meeting-2"),
        )
        connection.execute("UPDATE meetings SET title = 'Renamed Call' WHERE id = 'meeting-2'")

        result = publish_meeting(connection, "meeting-2", "obsidian")

    assert result.output_path.name == "2026-06-02 10-09-00 Renamed Call.md"
    assert "meeting_id: meeting-2" in result.output_path.read_text()
    assert "meeting_id: meeting-1" in first.output_path.read_text()


def test_republish_preserves_old_note_when_writing_replacement_fails(tmp_path: Path, monkeypatch) -> None:
    storage = ensure_storage_layout(tmp_path / "storage")
    with database(tmp_path / "fly.db") as connection:
        _export_test_meeting(connection, storage)
        add_publish_target(connection, "obsidian", tmp_path / "vault", "obsidian")
        first = publish_meeting(connection, "meeting-1", "obsidian")
        original_content = first.output_path.read_text()
        connection.execute("UPDATE meetings SET title = 'Renamed Call'")
        original_open = Path.open

        def fail_replacement_open(path: Path, mode: str = "r", *args, **kwargs):
            if mode == "x":
                raise OSError("Disk full")
            return original_open(path, mode, *args, **kwargs)

        monkeypatch.setattr(Path, "open", fail_replacement_open)
        with pytest.raises(OSError, match="Disk full"):
            publish_meeting(connection, "meeting-1", "obsidian")
        tracked_path = connection.execute("SELECT output_path FROM published_items").fetchone()[0]

    assert tracked_path == str(first.output_path)
    assert first.output_path.read_text() == original_content


def _export_test_meeting(connection: Connection, storage: StoragePaths, meeting_id: str = "meeting-1") -> None:
    connection.execute(
        "INSERT INTO meetings(id, slug, title, language, created_at) VALUES (?, ?, ?, ?, ?)",
        (meeting_id, meeting_id, "Intro Call", "sv", "2026-06-02 10:09:00"),
    )
    export_markdown_transcript(
        connection,
        meeting_id,
        "Person A: Hej där alla",
        "# Meeting Analysis\n\n## Summary\n\nUseful discussion.",
        storage,
    )
