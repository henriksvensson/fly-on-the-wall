import json
from pathlib import Path
from sqlite3 import Connection

from fly_on_the_wall.config import AppConfig
from fly_on_the_wall.db import database
from fly_on_the_wall.processing import process_audio
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
    assert "Unknown [sv] (speaker_0): Hej" in result.export.transcript_path.read_text()
