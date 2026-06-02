from pathlib import Path

import httpx
import pytest

from fly_on_the_wall.db import database
from fly_on_the_wall.providers.elevenlabs import (
    ElevenLabsError,
    run_transcription,
    transcribe_audio,
)
from fly_on_the_wall.storage import ensure_storage_layout


def test_transcribe_audio_posts_expected_request(tmp_path: Path) -> None:
    audio_path = tmp_path / "meeting.m4a"
    audio_path.write_bytes(b"audio")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://api.elevenlabs.io/v1/speech-to-text"
        assert request.headers["xi-api-key"] == "test-key"
        return httpx.Response(200, json={"text": "hej"})

    client = httpx.Client(transport=httpx.MockTransport(handler))

    assert transcribe_audio(audio_path, api_key="test-key", client=client) == {"text": "hej"}


def test_transcribe_audio_requires_api_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    audio_path = tmp_path / "meeting.m4a"
    audio_path.write_bytes(b"audio")
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)

    with pytest.raises(ElevenLabsError, match="Missing ELEVENLABS_API_KEY"):
        transcribe_audio(audio_path)


def test_run_transcription_stores_raw_response_and_provider_run(tmp_path: Path) -> None:
    audio_path = tmp_path / "meeting.m4a"
    audio_path.write_bytes(b"audio")
    storage = ensure_storage_layout(tmp_path / "storage")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"text": "hej"})

    client = httpx.Client(transport=httpx.MockTransport(handler))

    with database(tmp_path / "fly.db") as connection:
        connection.execute(
            "INSERT INTO meetings(id, slug, title, language) VALUES (?, ?, ?, ?)",
            ("meeting-1", "meeting-1", "Meeting", "sv"),
        )
        provider_run_id = run_transcription(
            connection, "meeting-1", audio_path, storage, client, api_key="test-key"
        )
        row = connection.execute(
            "SELECT * FROM provider_runs WHERE id = ?", (provider_run_id,)
        ).fetchone()

    assert row["provider"] == "elevenlabs"
    assert row["model"] == "scribe_v2"
    assert row["status"] == "done"
    assert Path(row["raw_response_path"]).read_text().strip() == '{\n  "text": "hej"\n}'
