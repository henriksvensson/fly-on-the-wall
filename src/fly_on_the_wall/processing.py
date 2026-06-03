from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from sqlite3 import Connection

from fly_on_the_wall.cache import read_cached_text, text_sha256, write_cached_text
from fly_on_the_wall.cleanup import deterministic_cleanup
from fly_on_the_wall.config import AppConfig
from fly_on_the_wall.embeddings import EmbeddingBackend
from fly_on_the_wall.exporting import ExportResult, export_markdown_transcript
from fly_on_the_wall.glossary import load_glossary_terms
from fly_on_the_wall.meetings import (
    Meeting,
    get_meeting,
    import_meeting,
    latest_completed_provider_run,
    update_generated_title,
)
from fly_on_the_wall.normalization import normalize_provider_run
from fly_on_the_wall.providers.elevenlabs import run_transcription
from fly_on_the_wall.providers.openai_analysis import (
    DEFAULT_ANALYSIS_MODEL,
    OpenAIAnalysisError,
    analyze_meeting,
    fallback_analysis,
    suggest_meeting_title,
)
from fly_on_the_wall.providers.openai_cleanup import (
    CLEANUP_PROMPT_VERSION,
    OpenAICleanupError,
    cleanup_transcript,
)
from fly_on_the_wall.providers.openai_cleanup import (
    DEFAULT_MODEL as DEFAULT_CLEANUP_MODEL,
)
from fly_on_the_wall.publishing import publish_enabled_targets
from fly_on_the_wall.recording_quality import (
    RecordingIgnoredError,
    assess_after_transcription,
    assess_before_transcription,
    store_recording_quality,
)
from fly_on_the_wall.rendering import render_named_transcript
from fly_on_the_wall.secrets import get_api_key
from fly_on_the_wall.speaker_identity import match_provider_run_speakers
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
    title: str | None,
    config: AppConfig,
    storage: StoragePaths | None = None,
    description: str | None = None,
    transcribe_fn: TranscribeFn | None = None,
    embedding_backend: EmbeddingBackend | None = None,
    progress: ProgressFn | None = None,
) -> ProcessResult:
    paths = storage or ensure_storage_layout()
    _report(progress, "Importing audio")
    meeting = import_meeting(connection, audio_path, title, config, paths, description)
    pre_quality = assess_before_transcription(connection, meeting)
    if pre_quality is not None:
        store_recording_quality(connection, meeting.id, pre_quality)
        if pre_quality.status in {"empty", "nonsense"}:
            _report(progress, f"Ignoring recording ({pre_quality.reason})")
            raise RecordingIgnoredError(meeting, pre_quality)

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
    export = _refresh_provider_run(
        connection,
        meeting,
        provider_run_id,
        config,
        paths,
        description,
        embedding_backend,
        progress,
    )
    _report(progress, "Done")
    return ProcessResult(_meeting_from_database(connection, meeting.id), provider_run_id, export)


def refresh_meeting(
    connection: Connection,
    meeting_id_or_slug: str,
    config: AppConfig,
    storage: StoragePaths | None = None,
    embedding_backend: EmbeddingBackend | None = None,
    progress: ProgressFn | None = None,
) -> ProcessResult:
    paths = storage or ensure_storage_layout()
    meeting_row = get_meeting(connection, meeting_id_or_slug)
    if meeting_row is None:
        raise ValueError(f"Meeting not found: {meeting_id_or_slug}")

    provider_run = latest_completed_provider_run(connection, meeting_row["id"])
    if provider_run is None:
        raise ValueError(f"No completed transcription found for meeting: {meeting_id_or_slug}")

    meeting = Meeting(
        id=meeting_row["id"],
        slug=meeting_row["slug"],
        title=meeting_row["title"],
        title_source=meeting_row.get("title_source", "manual"),
        language=meeting_row["language"],
        imported_audio_path=Path(meeting_row["imported_audio_path"]),
        audio_sha256=meeting_row.get("audio_sha256"),
        generated_title=meeting_row.get("generated_title"),
    )
    _report(progress, f"Refreshing meeting {meeting.slug}")
    export = _refresh_provider_run(
        connection,
        meeting,
        provider_run["id"],
        config,
        paths,
        meeting_row.get("description"),
        embedding_backend,
        progress,
    )
    _report(progress, "Done")
    return ProcessResult(_meeting_from_database(connection, meeting.id), provider_run["id"], export)


def _refresh_provider_run(
    connection: Connection,
    meeting: Meeting,
    provider_run_id: str,
    config: AppConfig,
    paths: StoragePaths,
    description: str | None,
    embedding_backend: EmbeddingBackend | None,
    progress: ProgressFn | None,
) -> ExportResult:
    _report(progress, "Normalizing transcript")
    segments = normalize_provider_run(connection, provider_run_id)
    quality = assess_after_transcription(connection, meeting, segments)
    store_recording_quality(connection, meeting.id, quality)
    if quality.status in {"empty", "nonsense"}:
        _report(progress, f"Ignoring recording ({quality.reason})")
        raise RecordingIgnoredError(meeting, quality)

    _report(progress, "Matching speaker identities")
    try:
        match_provider_run_speakers(connection, provider_run_id, embedding_backend, paths)
    except RuntimeError as exc:
        _report(progress, f"Speaker identity matching skipped ({exc})")
    _report(progress, "Rendering named transcript")
    named_transcript = render_named_transcript(connection, provider_run_id, storage=paths)
    _report(progress, "Running deterministic cleanup")
    deterministic_transcript = deterministic_cleanup(named_transcript)
    cleaned_transcript = deterministic_transcript

    if config.cleanup_mode == "light" and get_api_key("openai"):
        glossary_terms = load_glossary_terms(config.glossary_path)
        cleanup_cache_key = text_sha256(
            "\n".join(
                [
                    DEFAULT_CLEANUP_MODEL,
                    CLEANUP_PROMPT_VERSION,
                    description or "",
                    "\n".join(glossary_terms),
                    deterministic_transcript,
                ]
            )
        )
        cleanup_cache_dir = paths.artifacts / meeting.id / "llm-cleanup"
        cached_cleanup = read_cached_text(cleanup_cache_dir, cleanup_cache_key)
        if cached_cleanup is not None:
            _report(progress, "Reusing OpenAI light cleanup")
            cleaned_transcript = cached_cleanup
        else:
            _report(progress, "Running OpenAI light cleanup")
            try:
                cleaned_transcript = cleanup_transcript(
                    deterministic_transcript,
                    glossary_terms=glossary_terms,
                    meeting_context=description,
                )
                write_cached_text(cleanup_cache_dir, cleanup_cache_key, cleaned_transcript)
            except OpenAICleanupError as exc:
                _report(progress, f"OpenAI cleanup failed; exporting deterministic cleanup ({exc})")

    analysis = _analyze_transcript(paths, meeting.id, cleaned_transcript, description, progress)
    _suggest_and_apply_title(
        connection, paths, meeting.id, cleaned_transcript, analysis, description, progress
    )

    _report(progress, "Exporting markdown")
    export = export_markdown_transcript(connection, meeting.id, cleaned_transcript, analysis, paths)
    _publish_enabled_targets(connection, meeting.id, progress)
    return export


def _publish_enabled_targets(
    connection: Connection, meeting_id: str, progress: ProgressFn | None
) -> None:
    try:
        published = publish_enabled_targets(connection, meeting_id)
    except ValueError as exc:
        _report(progress, f"Publishing skipped ({exc})")
        return
    for result in published:
        _report(progress, f"Published to {result.target.name}: {result.output_path}")


def _suggest_and_apply_title(
    connection: Connection,
    storage: StoragePaths,
    meeting_id: str,
    transcript: str,
    analysis: str,
    description: str | None,
    progress: ProgressFn | None,
) -> None:
    if not get_api_key("openai"):
        return

    meeting = get_meeting(connection, meeting_id)
    if meeting is None:
        raise ValueError(f"Meeting not found: {meeting_id}")

    if meeting.get("title_source") == "manual":
        return

    title_cache_key = text_sha256(
        "\n".join([DEFAULT_ANALYSIS_MODEL, description or "", transcript, analysis])
    )
    title_cache_dir = storage.artifacts / meeting_id / "generated-title"
    cached_title = read_cached_text(title_cache_dir, title_cache_key)
    if cached_title is not None:
        _report(progress, "Reusing generated meeting title")
        generated_title = cached_title
    else:
        _report(progress, "Generating meeting title")
        try:
            generated_title = suggest_meeting_title(
                transcript,
                analysis,
                meeting_context=description,
            )
        except OpenAIAnalysisError as exc:
            _report(progress, f"Meeting title generation failed ({exc})")
            return
        write_cached_text(title_cache_dir, title_cache_key, generated_title)

    if generated_title.strip():
        update_generated_title(connection, meeting_id, generated_title)


def _run_elevenlabs_transcription(
    connection: Connection, meeting_id: str, audio_path: Path, storage: StoragePaths
) -> str:
    return run_transcription(connection, meeting_id, audio_path, storage)


def _meeting_from_database(connection: Connection, meeting_id: str) -> Meeting:
    row = get_meeting(connection, meeting_id)
    if row is None:
        raise ValueError(f"Meeting not found: {meeting_id}")
    return Meeting(
        id=row["id"],
        slug=row["slug"],
        title=row["title"],
        title_source=row.get("title_source", "manual"),
        language=row["language"],
        imported_audio_path=Path(row["imported_audio_path"]),
        audio_sha256=row.get("audio_sha256"),
        generated_title=row.get("generated_title"),
    )


def _report(progress: ProgressFn | None, message: str) -> None:
    if progress is not None:
        progress(message)


def _analyze_transcript(
    storage: StoragePaths,
    meeting_id: str,
    transcript: str,
    description: str | None,
    progress: ProgressFn | None,
) -> str:
    if not get_api_key("openai"):
        return fallback_analysis("OPENAI_API_KEY is missing")

    analysis_cache_key = text_sha256(
        "\n".join([DEFAULT_ANALYSIS_MODEL, description or "", transcript])
    )
    analysis_cache_dir = storage.artifacts / meeting_id / "analysis"
    cached_analysis = read_cached_text(analysis_cache_dir, analysis_cache_key)
    if cached_analysis is not None:
        _report(progress, "Reusing meeting analysis")
        return cached_analysis

    _report(progress, "Analyzing meeting")
    try:
        analysis = analyze_meeting(transcript, meeting_context=description)
    except OpenAIAnalysisError as exc:
        _report(progress, f"Meeting analysis failed; exporting fallback analysis ({exc})")
        return fallback_analysis(str(exc))

    write_cached_text(analysis_cache_dir, analysis_cache_key, analysis)
    return analysis
