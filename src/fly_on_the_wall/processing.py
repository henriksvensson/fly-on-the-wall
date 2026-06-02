from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from sqlite3 import Connection

from fly_on_the_wall.cleanup import deterministic_cleanup
from fly_on_the_wall.config import AppConfig
from fly_on_the_wall.exporting import ExportResult, export_markdown_transcript
from fly_on_the_wall.glossary import load_glossary_terms
from fly_on_the_wall.meetings import Meeting, import_meeting, latest_completed_provider_run
from fly_on_the_wall.normalization import normalize_provider_run
from fly_on_the_wall.providers.elevenlabs import run_transcription
from fly_on_the_wall.providers.openai_cleanup import cleanup_transcript
from fly_on_the_wall.rendering import render_named_transcript
from fly_on_the_wall.secrets import get_api_key
from fly_on_the_wall.storage import StoragePaths, ensure_storage_layout

TranscribeFn = Callable[[Connection, str, Path, StoragePaths], str]
ProgressFn = Callable[[str], None]


@dataclass(frozen=True)
class ProcessResult:
    meeting: Meeting
    provider_run_id: str
    export: ExportResult


def process_audio(
    connection: Connection,
    audio_path: Path,
    title: str,
    config: AppConfig,
    storage: StoragePaths | None = None,
    description: str | None = None,
    transcribe_fn: TranscribeFn | None = None,
    progress: ProgressFn | None = None,
) -> ProcessResult:
    paths = storage or ensure_storage_layout()
    _report(progress, "Importing audio")
    meeting = import_meeting(connection, audio_path, title, config, paths, description)
    existing_provider_run = latest_completed_provider_run(connection, meeting.id)
    if existing_provider_run is None:
        _report(progress, "Transcribing audio with ElevenLabs")
        resolved_transcribe = transcribe_fn or _run_elevenlabs_transcription
        provider_run_id = resolved_transcribe(
            connection, meeting.id, meeting.imported_audio_path, paths
        )
    else:
        _report(progress, "Reusing completed ElevenLabs transcription")
        provider_run_id = existing_provider_run["id"]
    _report(progress, "Normalizing transcript")
    normalize_provider_run(connection, provider_run_id)
    _report(progress, "Rendering named transcript")
    named_transcript = render_named_transcript(connection, provider_run_id, storage=paths)
    _report(progress, "Running deterministic cleanup")
    cleaned_transcript = deterministic_cleanup(named_transcript)

    if config.cleanup_mode == "light" and get_api_key("openai"):
        _report(progress, "Running OpenAI light cleanup")
        cleaned_transcript = cleanup_transcript(
            cleaned_transcript,
            glossary_terms=load_glossary_terms(config.glossary_path),
            meeting_context=description,
        )

    _report(progress, "Exporting markdown")
    export = export_markdown_transcript(connection, meeting.id, cleaned_transcript, paths)
    _report(progress, "Done")
    return ProcessResult(meeting, provider_run_id, export)


def _run_elevenlabs_transcription(
    connection: Connection, meeting_id: str, audio_path: Path, storage: StoragePaths
) -> str:
    return run_transcription(connection, meeting_id, audio_path, storage)


def _report(progress: ProgressFn | None, message: str) -> None:
    if progress is not None:
        progress(message)
