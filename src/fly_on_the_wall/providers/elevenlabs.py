from __future__ import annotations

import json
from pathlib import Path
from sqlite3 import Connection
from typing import Any
from uuid import uuid4

import httpx

from fly_on_the_wall.costs import record_service_usage
from fly_on_the_wall.secrets import get_api_key
from fly_on_the_wall.storage import StoragePaths, storage_paths

API_URL = "https://api.elevenlabs.io/v1/speech-to-text"
PROVIDER = "elevenlabs"
MODEL = "scribe_v2"


class ElevenLabsError(RuntimeError):
    """Raised when ElevenLabs transcription fails."""


def transcribe_audio(
    audio_path: Path,
    api_key: str | None = None,
    client: httpx.Client | None = None,
    num_speakers: int | None = None,
    diarization_threshold: float | None = None,
    no_verbatim: bool = False,
    keyterms: list[str] | None = None,
) -> dict[str, Any]:
    resolved_api_key = api_key or get_api_key(PROVIDER)
    if not resolved_api_key:
        raise ElevenLabsError("Missing ELEVENLABS_API_KEY.")

    form_fields = [
        ("model_id", MODEL),
        ("tag_audio_events", "true"),
        ("timestamps_granularity", "word"),
        ("diarize", "true"),
        ("temperature", "0"),
        ("seed", "1"),
        ("no_verbatim", str(no_verbatim).lower()),
    ]
    if num_speakers is not None:
        form_fields.append(("num_speakers", str(num_speakers)))
    if diarization_threshold is not None:
        form_fields.append(("diarization_threshold", str(diarization_threshold)))
    if keyterms:
        form_fields.extend(("keyterms", keyterm) for keyterm in keyterms)

    close_client = client is None
    http_client = client or httpx.Client(timeout=600)
    try:
        with audio_path.open("rb") as audio_file:
            files: list[tuple[str, Any]] = [(name, (None, value)) for name, value in form_fields]
            files.append(("file", (audio_path.name, audio_file)))
            response = http_client.post(
                API_URL,
                headers={"xi-api-key": resolved_api_key},
                files=files,
            )
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as exc:
        message = f"ElevenLabs HTTP {exc.response.status_code}: {exc.response.text}"
        raise ElevenLabsError(message) from exc
    except httpx.HTTPError as exc:
        raise ElevenLabsError(f"ElevenLabs request failed: {exc}") from exc
    finally:
        if close_client:
            http_client.close()


def run_transcription(
    connection: Connection,
    meeting_id: str,
    audio_path: Path,
    storage: StoragePaths | None = None,
    client: httpx.Client | None = None,
    api_key: str | None = None,
    keyterms: list[str] | None = None,
) -> str:
    paths = storage or storage_paths()
    provider_run_id = str(uuid4())
    raw_response_path = paths.artifacts / meeting_id / "provider-runs" / f"{provider_run_id}.raw.json"
    raw_response_path.parent.mkdir(parents=True, exist_ok=True)

    settings = {"keyterms": keyterms or []}
    _insert_provider_run(connection, provider_run_id, meeting_id, raw_response_path, "running", settings)
    try:
        response = transcribe_audio(audio_path, api_key=api_key, client=client, keyterms=keyterms)
        raw_response_path.write_text(json.dumps(response, indent=2, ensure_ascii=False) + "\n")
        duration = float(response.get("audio_duration_secs") or 0)
        record_service_usage(
            connection,
            meeting_id=meeting_id,
            provider_run_id=provider_run_id,
            provider=PROVIDER,
            model=MODEL,
            service="transcription",
            unit="audio_second",
            input_quantity=duration,
            usage={"audio_duration_secs": duration},
        )
    except Exception:
        _set_provider_run_status(connection, provider_run_id, "failed")
        raise

    _set_provider_run_status(connection, provider_run_id, "done")
    return provider_run_id


def _insert_provider_run(
    connection: Connection,
    provider_run_id: str,
    meeting_id: str,
    raw_response_path: Path,
    status: str,
    settings: dict[str, Any] | None = None,
) -> None:
    with connection:
        connection.execute(
            """
            INSERT INTO provider_runs(
                id,
                meeting_id,
                provider,
                model,
                settings_json,
                raw_response_path,
                status
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                provider_run_id,
                meeting_id,
                PROVIDER,
                MODEL,
                json.dumps(settings or {}, sort_keys=True),
                str(raw_response_path),
                status,
            ),
        )


def _set_provider_run_status(connection: Connection, provider_run_id: str, status: str) -> None:
    with connection:
        connection.execute(
            """
            UPDATE provider_runs
            SET status = ?,
                completed_at = CASE
                    WHEN ? = 'done' THEN CURRENT_TIMESTAMP
                    ELSE completed_at
                END
            WHERE id = ?
            """,
            (status, status, provider_run_id),
        )
