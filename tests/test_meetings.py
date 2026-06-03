from pathlib import Path

from fly_on_the_wall.config import AppConfig
from fly_on_the_wall.db import database
from fly_on_the_wall.meetings import (
    delete_meeting,
    file_sha256,
    import_meeting,
    latest_completed_provider_run,
    rename_meeting,
    slugify,
    update_generated_title,
)
from fly_on_the_wall.storage import ensure_storage_layout


def test_slugify_normalizes_titles() -> None:
    assert slugify("Intro Call With Person B!") == "intro-call-with-person_b"
    assert slugify("!!!") == "meeting"


def test_import_meeting_copies_audio_and_creates_record(tmp_path: Path, monkeypatch) -> None:
    audio_path = tmp_path / "source.m4a"
    audio_path.write_bytes(b"fake audio")
    storage = ensure_storage_layout(tmp_path / "storage")
    monkeypatch.setattr(
        "fly_on_the_wall.audio_metadata.probe_metadata",
        lambda path: {
            "streams": [{"codec_type": "audio", "codec_name": "mp3", "sample_rate": "44100"}],
            "format": {
                "format_name": "mp3",
                "duration": "12.5",
                "size": "12345",
                "tags": {"title": "2026-06-03 10:55:36 Custom"},
            },
        },
    )

    with database(tmp_path / "fly.db") as connection:
        meeting = import_meeting(
            connection,
            audio_path,
            "Intro Call With Person B",
            AppConfig(language="sv"),
            storage,
            description="First call",
        )
        row = connection.execute("SELECT * FROM meetings WHERE id = ?", (meeting.id,)).fetchone()
        metadata = connection.execute(
            "SELECT * FROM audio_metadata WHERE meeting_id = ?", (meeting.id,)
        ).fetchone()

    assert meeting.slug == "intro-call-with-person_b"
    assert meeting.imported_audio_path.read_bytes() == b"fake audio"
    assert row["title"] == "Intro Call With Person B"
    assert row["title_source"] == "manual"
    assert row["description"] == "First call"
    assert row["language"] == "sv"
    assert row["audio_sha256"] == file_sha256(audio_path)
    assert metadata["recorded_at"] == "2026-06-03 10:55:36"
    assert metadata["recorded_at_confidence"] == "high"
    assert metadata["duration_seconds"] == 12.5
    assert Path(metadata["raw_metadata_path"]).exists()


def test_import_meeting_uses_filename_as_provisional_title(tmp_path: Path) -> None:
    audio_path = tmp_path / "Weekly Planning.m4a"
    audio_path.write_bytes(b"fake audio")
    storage = ensure_storage_layout(tmp_path / "storage")

    with database(tmp_path / "fly.db") as connection:
        meeting = import_meeting(connection, audio_path, None, AppConfig(), storage)
        row = connection.execute("SELECT * FROM meetings WHERE id = ?", (meeting.id,)).fetchone()

    assert meeting.title == "Weekly Planning"
    assert meeting.title_source == "filename"
    assert row["title_source"] == "filename"


def test_generated_title_replaces_filename_title_only(tmp_path: Path) -> None:
    filename_audio = tmp_path / "recording.m4a"
    filename_audio.write_bytes(b"filename audio")
    manual_audio = tmp_path / "manual.m4a"
    manual_audio.write_bytes(b"manual audio")
    storage = ensure_storage_layout(tmp_path / "storage")

    with database(tmp_path / "fly.db") as connection:
        filename_meeting = import_meeting(connection, filename_audio, None, AppConfig(), storage)
        manual_meeting = import_meeting(
            connection, manual_audio, "Manual Title", AppConfig(), storage
        )
        update_generated_title(connection, filename_meeting.id, "Recruitment Planning")
        update_generated_title(connection, manual_meeting.id, "Generated Suggestion")
        filename_row = connection.execute(
            "SELECT * FROM meetings WHERE id = ?", (filename_meeting.id,)
        ).fetchone()
        manual_row = connection.execute(
            "SELECT * FROM meetings WHERE id = ?", (manual_meeting.id,)
        ).fetchone()

    assert filename_row["title"] == "Recruitment Planning"
    assert filename_row["title_source"] == "generated"
    assert filename_row["generated_title"] == "Recruitment Planning"
    assert manual_row["title"] == "Manual Title"
    assert manual_row["title_source"] == "manual"
    assert manual_row["generated_title"] == "Generated Suggestion"


def test_rename_meeting_sets_manual_title_override(tmp_path: Path) -> None:
    audio_path = tmp_path / "recording.m4a"
    audio_path.write_bytes(b"fake audio")
    storage = ensure_storage_layout(tmp_path / "storage")

    with database(tmp_path / "fly.db") as connection:
        meeting = import_meeting(connection, audio_path, None, AppConfig(), storage)
        update_generated_title(connection, meeting.id, "Generated Title")
        updated = rename_meeting(connection, meeting.slug, "Manual Rename")

    assert updated["title"] == "Manual Rename"
    assert updated["title_source"] == "manual"


def test_import_meeting_generates_unique_slug(tmp_path: Path) -> None:
    first_audio_path = tmp_path / "source-1.m4a"
    first_audio_path.write_bytes(b"fake audio 1")
    second_audio_path = tmp_path / "source-2.m4a"
    second_audio_path.write_bytes(b"fake audio 2")
    storage = ensure_storage_layout(tmp_path / "storage")

    with database(tmp_path / "fly.db") as connection:
        first = import_meeting(connection, first_audio_path, "Same Title", AppConfig(), storage)
        second = import_meeting(connection, second_audio_path, "Same Title", AppConfig(), storage)

    assert first.slug == "same-title"
    assert second.slug == "same-title-2"


def test_import_meeting_reuses_existing_meeting_for_same_audio_hash(tmp_path: Path) -> None:
    first_audio_path = tmp_path / "source-1.m4a"
    first_audio_path.write_bytes(b"same audio")
    second_audio_path = tmp_path / "source-2.m4a"
    second_audio_path.write_bytes(b"same audio")
    storage = ensure_storage_layout(tmp_path / "storage")

    with database(tmp_path / "fly.db") as connection:
        first = import_meeting(connection, first_audio_path, "First Title", AppConfig(), storage)
        second = import_meeting(connection, second_audio_path, "Second Title", AppConfig(), storage)
        meeting_count = connection.execute(
            "SELECT COUNT(*) AS count FROM meetings"
        ).fetchone()["count"]

    assert first.id == second.id
    assert second.title == "First Title"
    assert meeting_count == 1


def test_latest_completed_provider_run_returns_most_recent_done_run(tmp_path: Path) -> None:
    with database(tmp_path / "fly.db") as connection:
        connection.execute(
            "INSERT INTO meetings(id, slug, title, language) VALUES (?, ?, ?, ?)",
            ("meeting-1", "intro", "Intro", "sv"),
        )
        connection.execute(
            """
            INSERT INTO provider_runs(id, meeting_id, provider, model, raw_response_path, status)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("failed-run", "meeting-1", "elevenlabs", "scribe_v2", "raw.json", "failed"),
        )
        connection.execute(
            """
            INSERT INTO provider_runs(id, meeting_id, provider, model, raw_response_path, status)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("done-run", "meeting-1", "elevenlabs", "scribe_v2", "raw.json", "done"),
        )

        provider_run = latest_completed_provider_run(connection, "meeting-1")

    assert provider_run["id"] == "done-run"


def test_delete_meeting_removes_database_rows_and_owned_files(tmp_path: Path) -> None:
    storage = ensure_storage_layout(tmp_path / "storage")
    audio_dir = storage.audio / "intro"
    audio_dir.mkdir(parents=True)
    imported_audio_path = audio_dir / "source.m4a"
    imported_audio_path.write_bytes(b"audio")
    artifact_dir = storage.artifacts / "meeting-1"
    artifact_dir.mkdir(parents=True)
    artifact_path = artifact_dir / "raw.json"
    artifact_path.write_text("{}")
    export_dir = storage.exports / "intro" / "snapshot"
    export_dir.mkdir(parents=True)
    manifest_path = export_dir / "manifest.json"
    manifest_path.write_text("{}")
    voice_sample_path = storage.voice_samples / "person-1" / "sample.wav"
    voice_sample_path.parent.mkdir(parents=True)
    voice_sample_path.write_bytes(b"voice")
    embedding_path = storage.artifacts / "embeddings" / "voice.json"
    embedding_path.parent.mkdir(parents=True)
    embedding_path.write_text("{}")

    with database(tmp_path / "fly.db") as connection:
        connection.execute(
            """
            INSERT INTO meetings(id, slug, title, language, imported_audio_path)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("meeting-1", "intro", "Intro", "sv", str(imported_audio_path)),
        )
        connection.execute(
            "INSERT INTO people(id, display_name) VALUES (?, ?)", ("person-1", "Person B")
        )
        connection.execute(
            """
            INSERT INTO provider_runs(id, meeting_id, provider, model, raw_response_path, status)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("run-1", "meeting-1", "elevenlabs", "scribe_v2", str(artifact_path), "done"),
        )
        connection.execute(
            """
            INSERT INTO local_speakers(id, meeting_id, provider_run_id, label)
            VALUES (?, ?, ?, ?)
            """,
            ("speaker-1", "meeting-1", "run-1", "speaker_0"),
        )
        connection.execute(
            """
            INSERT INTO segments(id, meeting_id, provider_run_id, local_speaker_id, sequence, text)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("segment-1", "meeting-1", "run-1", "speaker-1", 0, "Hej"),
        )
        connection.execute(
            """
            INSERT INTO corrections(id, correction_type, meeting_id, local_speaker_id)
            VALUES (?, ?, ?, ?)
            """,
            ("correction-1", "speaker_assignment", "meeting-1", "speaker-1"),
        )
        connection.execute(
            """
            INSERT INTO exports(id, meeting_id, format, output_dir, manifest_path)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("export-1", "meeting-1", "markdown", str(export_dir), str(manifest_path)),
        )
        connection.execute(
            """
            INSERT INTO voice_samples(
                id, person_id, source_meeting_id, audio_path, embedding_path
            ) VALUES (?, ?, ?, ?, ?)
            """,
            ("voice-1", "person-1", "meeting-1", str(voice_sample_path), str(embedding_path)),
        )

        result = delete_meeting(connection, "intro", storage)

        assert connection.execute("SELECT COUNT(*) FROM meetings").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM provider_runs").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM local_speakers").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM segments").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM corrections").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM exports").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM voice_samples").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM people").fetchone()[0] == 1

    assert result.slug == "intro"
    assert not audio_dir.exists()
    assert not artifact_dir.exists()
    assert not (storage.exports / "intro").exists()
    assert not voice_sample_path.exists()
    assert not embedding_path.exists()
