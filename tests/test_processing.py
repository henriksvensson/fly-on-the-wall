import json
from pathlib import Path
from sqlite3 import Connection

from fly_on_the_wall.config import AppConfig
from fly_on_the_wall.db import database
from fly_on_the_wall.processing import process_audio
from fly_on_the_wall.providers.openai_cleanup import OpenAICleanupError
from fly_on_the_wall.storage import StoragePaths, ensure_storage_layout


def test_process_audio_runs_to_markdown_export(tmp_path: Path) -> None:
    audio_path = tmp_path / "meeting.m4a"
    audio_path.write_bytes(b"audio")
    storage = ensure_storage_layout(tmp_path / "storage")

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
                        {"speaker_id": "speaker_0", "text": "Hej", "start": 0, "end": 0.2}
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
        result = process_audio(
            connection,
            audio_path,
            "Intro Call",
            AppConfig(cleanup_mode="deterministic"),
            storage,
            transcribe_fn=fake_transcribe,
        )

    assert result.export.transcript_path.exists()
    assert "**Unknown speaker 1:** Hej" in result.export.transcript_path.read_text()


def test_process_audio_reuses_existing_meeting_and_provider_run(tmp_path: Path) -> None:
    audio_path = tmp_path / "meeting.m4a"
    audio_path.write_bytes(b"audio")
    storage = ensure_storage_layout(tmp_path / "storage")
    calls = 0

    def fake_transcribe(
        connection: Connection, meeting_id: str, audio_path: Path, storage: StoragePaths
    ) -> str:
        nonlocal calls
        calls += 1
        raw_path = storage.artifacts / meeting_id / "raw.json"
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_text(
            json.dumps(
                {
                    "language_code": "sv",
                    "words": [
                        {"speaker_id": "speaker_0", "text": "Hej", "start": 0, "end": 0.2}
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

    def fail_if_called(
        connection: Connection, meeting_id: str, audio_path: Path, storage: StoragePaths
    ) -> str:
        raise AssertionError("duplicate audio should reuse the completed provider run")

    with database(tmp_path / "fly.db") as connection:
        first = process_audio(
            connection,
            audio_path,
            "Intro Call",
            AppConfig(cleanup_mode="deterministic"),
            storage,
            transcribe_fn=fake_transcribe,
        )
        second = process_audio(
            connection,
            audio_path,
            "Duplicate Title",
            AppConfig(cleanup_mode="deterministic"),
            storage,
            transcribe_fn=fail_if_called,
        )
        meeting_count = connection.execute(
            "SELECT COUNT(*) AS count FROM meetings"
        ).fetchone()["count"]

    assert first.meeting.id == second.meeting.id
    assert second.provider_run_id == "run-1"
    assert calls == 1
    assert meeting_count == 1


def test_process_audio_reports_progress(tmp_path: Path) -> None:
    audio_path = tmp_path / "meeting.m4a"
    audio_path.write_bytes(b"audio")
    storage = ensure_storage_layout(tmp_path / "storage")
    progress_messages: list[str] = []

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
                        {"speaker_id": "speaker_0", "text": "Hej", "start": 0, "end": 0.2}
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
        process_audio(
            connection,
            audio_path,
            "Intro Call",
            AppConfig(cleanup_mode="deterministic"),
            storage,
            transcribe_fn=fake_transcribe,
            progress=progress_messages.append,
        )

    assert progress_messages == [
        "Importing audio",
        "Transcribing audio with ElevenLabs",
        "Normalizing transcript",
        "Rendering named transcript",
        "Running deterministic cleanup",
        "Exporting markdown",
        "Done",
    ]


def test_process_audio_exports_when_openai_cleanup_fails(tmp_path: Path, monkeypatch) -> None:
    audio_path = tmp_path / "meeting.m4a"
    audio_path.write_bytes(b"audio")
    storage = ensure_storage_layout(tmp_path / "storage")
    progress_messages: list[str] = []

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
                        {"speaker_id": "speaker_0", "text": "Hej", "start": 0, "end": 0.2}
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

    def fail_cleanup(*args, **kwargs) -> str:
        raise OpenAICleanupError("timeout")

    monkeypatch.setattr("fly_on_the_wall.processing.get_api_key", lambda provider: "test-key")
    monkeypatch.setattr("fly_on_the_wall.processing.cleanup_transcript", fail_cleanup)

    with database(tmp_path / "fly.db") as connection:
        result = process_audio(
            connection,
            audio_path,
            "Intro Call",
            AppConfig(cleanup_mode="light"),
            storage,
            transcribe_fn=fake_transcribe,
            progress=progress_messages.append,
        )

    assert result.export.transcript_path.exists()
    assert "**Unknown speaker 1:** Hej" in result.export.transcript_path.read_text()
    assert any(message.startswith("OpenAI cleanup failed") for message in progress_messages)
