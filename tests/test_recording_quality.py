from pathlib import Path
from types import SimpleNamespace

import pytest

from fly_on_the_wall.config import AppConfig
from fly_on_the_wall.db import database
from fly_on_the_wall.meetings import Meeting
from fly_on_the_wall.processing import process_audio
from fly_on_the_wall.recording_quality import RecordingIgnoredError
from fly_on_the_wall.storage import StoragePaths, ensure_storage_layout
from fly_on_the_wall.watch import add_watch_folder, scan_watch_folders


def test_process_audio_ignores_very_short_audio_before_transcription(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    audio_path = tmp_path / "short.mp3"
    audio_path.write_bytes(b"audio")
    storage = ensure_storage_layout(tmp_path / "storage")
    transcribe_called = False

    monkeypatch.setattr(
        "fly_on_the_wall.audio_metadata.probe_metadata",
        lambda path: {"streams": [], "format": {"duration": "2.5", "size": "100"}},
    )

    def fake_transcribe(connection, meeting_id: str, audio_path: Path, storage: StoragePaths) -> str:
        nonlocal transcribe_called
        transcribe_called = True
        return "run-1"

    with database(tmp_path / "fly.db") as connection:
        with pytest.raises(RecordingIgnoredError) as error:
            process_audio(
                connection,
                audio_path,
                None,
                AppConfig(cleanup_mode="deterministic"),
                storage,
                transcribe_fn=fake_transcribe,
            )
        quality = connection.execute("SELECT * FROM recording_quality").fetchone()

    assert not transcribe_called
    assert error.value.quality.reason == "audio_too_short"
    assert quality["status"] == "empty"
    assert quality["reason"] == "audio_too_short"


def test_process_audio_ignores_empty_transcript_after_transcription(tmp_path: Path) -> None:
    audio_path = tmp_path / "empty.mp3"
    audio_path.write_bytes(b"audio")
    storage = ensure_storage_layout(tmp_path / "storage")

    def fake_transcribe(connection, meeting_id: str, audio_path: Path, storage: StoragePaths) -> str:
        raw_path = storage.artifacts / meeting_id / "raw.json"
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_text('{"language_code":"sv","words":[]}')
        connection.execute(
            """
            INSERT INTO provider_runs(id, meeting_id, provider, model, raw_response_path, status)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("run-1", meeting_id, "elevenlabs", "scribe_v2", str(raw_path), "done"),
        )
        return "run-1"

    with database(tmp_path / "fly.db") as connection:
        with pytest.raises(RecordingIgnoredError) as error:
            process_audio(
                connection,
                audio_path,
                None,
                AppConfig(cleanup_mode="deterministic"),
                storage,
                transcribe_fn=fake_transcribe,
            )
        export_count = connection.execute("SELECT COUNT(*) FROM exports").fetchone()[0]

    assert error.value.quality.reason == "no_transcript_segments"
    assert export_count == 0


def test_process_audio_records_sparse_transcript_as_suspicious(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    audio_path = tmp_path / "sparse.mp3"
    audio_path.write_bytes(b"audio")
    storage = ensure_storage_layout(tmp_path / "storage")

    monkeypatch.setattr(
        "fly_on_the_wall.audio_metadata.probe_metadata",
        lambda path: {"streams": [], "format": {"duration": "20", "size": "100"}},
    )

    def fake_transcribe(connection, meeting_id: str, audio_path: Path, storage: StoragePaths) -> str:
        raw_path = storage.artifacts / meeting_id / "raw.json"
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_text(
            '{"language_code":"sv","words":[{"speaker_id":"speaker_0","text":"Hej","start":0,"end":0.2}]}'
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
        result = process_audio(
            connection,
            audio_path,
            None,
            AppConfig(cleanup_mode="deterministic"),
            storage,
            transcribe_fn=fake_transcribe,
        )
        quality = connection.execute("SELECT * FROM recording_quality").fetchone()

    assert result.export.transcript_path.exists()
    assert quality["status"] == "suspicious"
    assert quality["reason"] == "too_few_meaningful_words"


def test_watch_scan_marks_ignored_recordings(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    audio_path = inbox / "short.mp3"
    audio_path.write_bytes(b"audio")

    def fake_process(connection, path, title, config, storage=None, progress=None):
        connection.execute(
            "INSERT INTO meetings(id, slug, title, language) VALUES (?, ?, ?, ?)",
            ("meeting-1", "short", "short", "sv"),
        )
        meeting = Meeting(
            id="meeting-1",
            slug="short",
            title="short",
            title_source="filename",
            language="sv",
            imported_audio_path=path,
        )
        quality = SimpleNamespace(status="empty", reason="audio_too_short", details={})
        raise RecordingIgnoredError(meeting, quality)

    with database(tmp_path / "fly.db") as connection:
        add_watch_folder(connection, inbox, delete_originals_after_import=True)
        result = scan_watch_folders(connection, AppConfig(), process_fn=fake_process, stable_age_seconds=0)
        item = connection.execute("SELECT * FROM watch_items WHERE path = ?", (str(audio_path),)).fetchone()

    assert result.ignored == 1
    assert item["status"] == "ignored"
    assert item["error_message"] == "audio_too_short"
    assert audio_path.exists()
