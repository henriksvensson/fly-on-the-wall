from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from sqlite3 import Connection

from fly_on_the_wall.cache import read_cached_text, text_sha256, write_cached_text
from fly_on_the_wall.cleanup import deterministic_cleanup
from fly_on_the_wall.config import AppConfig
from fly_on_the_wall.costs import record_openai_usage
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
    AnalysisRequest,
    OpenAIAnalysisError,
    OpenAIRequestOptions,
    TitleRequest,
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


@dataclass(frozen=True)
class RefreshContext:
    connection: Connection
    meeting: Meeting
    config: AppConfig
    paths: StoragePaths
    description: str | None
    embedding_backend: EmbeddingBackend | None
    progress: TimedProgress


@dataclass(frozen=True)
class TranscriptArtifacts:
    deterministic: str
    cleaned: str


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
    timed_progress = TimedProgress(progress)
    with timed_progress.step("Importing audio"):
        meeting = import_meeting(connection, audio_path, title, config, paths, description)
    timed_progress.message(f"Audio duration: {_audio_duration_label(connection, meeting.id)}")
    pre_quality = assess_before_transcription(connection, meeting)
    if pre_quality is not None:
        store_recording_quality(connection, meeting.id, pre_quality)
        if pre_quality.status in {"empty", "nonsense"}:
            timed_progress.message(f"Ignoring recording ({pre_quality.reason})")
            raise RecordingIgnoredError(meeting, pre_quality)

    existing_provider_run = latest_completed_provider_run(connection, meeting.id)
    if existing_provider_run is None:
        with timed_progress.step("Transcribing audio with ElevenLabs"):
            resolved_transcribe = transcribe_fn or _run_elevenlabs_transcription
            provider_run_id = resolved_transcribe(connection, meeting.id, meeting.imported_audio_path, paths)
    else:
        timed_progress.message("Reusing completed ElevenLabs transcription")
        provider_run_id = existing_provider_run["id"]
    context = RefreshContext(connection, meeting, config, paths, description, embedding_backend, timed_progress)
    export = _refresh_provider_run(context, provider_run_id)
    timed_progress.message(f"Done ({timed_progress.total_elapsed()})")
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
    timed_progress = TimedProgress(progress)
    timed_progress.message(f"Refreshing meeting {meeting.slug}")
    context = RefreshContext(
        connection,
        meeting,
        config,
        paths,
        meeting_row.get("description"),
        embedding_backend,
        timed_progress,
    )
    export = _refresh_provider_run(context, provider_run["id"])
    timed_progress.message(f"Done ({timed_progress.total_elapsed()})")
    return ProcessResult(_meeting_from_database(connection, meeting.id), provider_run["id"], export)


def _refresh_provider_run(context: RefreshContext, provider_run_id: str) -> ExportResult:
    with context.progress.step("Normalizing transcript"):
        segments = normalize_provider_run(context.connection, provider_run_id)
    quality = assess_after_transcription(context.connection, context.meeting, segments)
    store_recording_quality(context.connection, context.meeting.id, quality)
    if quality.status in {"empty", "nonsense"}:
        context.progress.message(f"Ignoring recording ({quality.reason})")
        raise RecordingIgnoredError(context.meeting, quality)

    with context.progress.step("Matching speaker identities"):
        try:
            match_provider_run_speakers(
                context.connection,
                provider_run_id,
                context.embedding_backend,
                context.paths,
            )
        except RuntimeError as exc:
            context.progress.message(f"Speaker identity matching skipped ({exc})")
    with context.progress.step("Rendering named transcript"):
        named_transcript = render_named_transcript(context.connection, provider_run_id, storage=context.paths)
    with context.progress.step("Running deterministic cleanup"):
        deterministic_transcript = deterministic_cleanup(named_transcript)
    artifacts = _cleanup_transcript(context, deterministic_transcript)
    analysis = _analyze_transcript(context, artifacts.cleaned)
    _suggest_and_apply_title(context, artifacts.cleaned, analysis)

    with context.progress.step("Exporting markdown"):
        export = export_markdown_transcript(
            context.connection, context.meeting.id, artifacts.cleaned, analysis, context.paths
        )
    _publish_enabled_targets(context.connection, context.meeting.id, context.progress)
    return export


def _cleanup_transcript(context: RefreshContext, deterministic_transcript: str) -> TranscriptArtifacts:
    if context.config.cleanup_mode != "light" or not get_api_key("openai"):
        return TranscriptArtifacts(deterministic_transcript, deterministic_transcript)

    glossary_terms = load_glossary_terms(context.config.glossary_path)
    cleanup_cache_key = text_sha256(
        "\n".join(
            [
                DEFAULT_CLEANUP_MODEL,
                CLEANUP_PROMPT_VERSION,
                context.description or "",
                "\n".join(glossary_terms),
                deterministic_transcript,
            ]
        )
    )
    cleanup_cache_dir = context.paths.artifacts / context.meeting.id / "llm-cleanup"
    cached_cleanup = read_cached_text(cleanup_cache_dir, cleanup_cache_key)
    if cached_cleanup is not None:
        context.progress.message("Reusing OpenAI light cleanup")
        return TranscriptArtifacts(deterministic_transcript, cached_cleanup)

    with context.progress.step("Running OpenAI light cleanup"):
        try:
            cleaned_transcript = cleanup_transcript(
                deterministic_transcript,
                glossary_terms=glossary_terms,
                meeting_context=context.description,
                usage_callback=lambda response: record_openai_usage(
                    context.connection,
                    meeting_id=context.meeting.id,
                    model=DEFAULT_CLEANUP_MODEL,
                    service="cleanup",
                    response=response,
                ),
            )
            write_cached_text(cleanup_cache_dir, cleanup_cache_key, cleaned_transcript)
            return TranscriptArtifacts(deterministic_transcript, cleaned_transcript)
        except OpenAICleanupError as exc:
            context.progress.message(f"OpenAI cleanup failed; exporting deterministic cleanup ({exc})")
            return TranscriptArtifacts(deterministic_transcript, deterministic_transcript)


def _publish_enabled_targets(connection: Connection, meeting_id: str, progress: TimedProgress) -> None:
    try:
        published = publish_enabled_targets(connection, meeting_id)
    except ValueError as exc:
        progress.message(f"Publishing skipped ({exc})")
        return
    for result in published:
        progress.message(f"Published to {result.target.name}: {result.output_path}")


def _suggest_and_apply_title(
    context: RefreshContext,
    transcript: str,
    analysis: str,
) -> None:
    if not get_api_key("openai"):
        return

    meeting = get_meeting(context.connection, context.meeting.id)
    if meeting is None:
        raise ValueError(f"Meeting not found: {context.meeting.id}")

    if meeting.get("title_source") == "manual":
        return

    title_cache_key = text_sha256("\n".join([DEFAULT_ANALYSIS_MODEL, context.description or "", transcript, analysis]))
    title_cache_dir = context.paths.artifacts / context.meeting.id / "generated-title"
    cached_title = read_cached_text(title_cache_dir, title_cache_key)
    if cached_title is not None:
        context.progress.message("Reusing generated meeting title")
        generated_title = cached_title
    else:
        with context.progress.step("Generating meeting title"):
            try:
                generated_title = suggest_meeting_title(
                    TitleRequest(
                        transcript,
                        analysis,
                        meeting_context=context.description,
                        options=OpenAIRequestOptions(
                            usage_callback=lambda response: record_openai_usage(
                                context.connection,
                                meeting_id=context.meeting.id,
                                model=DEFAULT_ANALYSIS_MODEL,
                                service="title",
                                response=response,
                            )
                        ),
                    ),
                )
            except OpenAIAnalysisError as exc:
                context.progress.message(f"Meeting title generation failed ({exc})")
                return
            write_cached_text(title_cache_dir, title_cache_key, generated_title)

    if generated_title.strip():
        update_generated_title(context.connection, context.meeting.id, generated_title)


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


class TimedProgress:
    def __init__(self, progress: ProgressFn | None) -> None:
        self.progress = progress
        self.started_at = time.monotonic()

    def message(self, message: str) -> None:
        _report(self.progress, message)

    def step(self, label: str) -> TimedStep:
        return TimedStep(self, label)

    def total_elapsed(self) -> str:
        return _format_elapsed(time.monotonic() - self.started_at)


class TimedStep:
    def __init__(self, progress: TimedProgress, label: str) -> None:
        self.progress = progress
        self.label = label
        self.started_at = 0.0

    def __enter__(self) -> None:
        self.started_at = time.monotonic()
        self.progress.message(self.label)

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        elapsed = _format_elapsed(time.monotonic() - self.started_at)
        self.progress.message(f"{self.label} completed in {elapsed}")


def _audio_duration_label(connection: Connection, meeting_id: str) -> str:
    duration = _audio_duration_from_metadata(connection, meeting_id)
    if duration is None:
        return "Unknown"
    return _format_duration(duration)


def _audio_duration_from_metadata(connection: Connection, meeting_id: str) -> float | None:
    row = connection.execute(
        "SELECT duration_seconds FROM audio_metadata WHERE meeting_id = ?",
        (meeting_id,),
    ).fetchone()
    if row is None or row["duration_seconds"] is None:
        return None
    return float(row["duration_seconds"])


def _format_duration(seconds: float) -> str:
    total_seconds = int(seconds)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes}m {seconds}s"
    if minutes:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


def _format_elapsed(seconds: float) -> str:
    if seconds < 1:
        return f"{seconds:.2f}s"
    return _format_duration(seconds)


def _analyze_transcript(
    context: RefreshContext,
    transcript: str,
) -> str:
    if not get_api_key("openai"):
        return fallback_analysis("OPENAI_API_KEY is missing")

    analysis_cache_key = text_sha256("\n".join([DEFAULT_ANALYSIS_MODEL, context.description or "", transcript]))
    analysis_cache_dir = context.paths.artifacts / context.meeting.id / "analysis"
    cached_analysis = read_cached_text(analysis_cache_dir, analysis_cache_key)
    if cached_analysis is not None:
        context.progress.message("Reusing meeting analysis")
        return cached_analysis

    with context.progress.step("Analyzing meeting"):
        try:
            analysis = analyze_meeting(
                AnalysisRequest(
                    transcript,
                    meeting_context=context.description,
                    options=OpenAIRequestOptions(
                        usage_callback=lambda response: record_openai_usage(
                            context.connection,
                            meeting_id=context.meeting.id,
                            model=DEFAULT_ANALYSIS_MODEL,
                            service="analysis",
                            response=response,
                        )
                    ),
                ),
            )
        except OpenAIAnalysisError as exc:
            context.progress.message(f"Meeting analysis failed; exporting fallback analysis ({exc})")
            return fallback_analysis(str(exc))

    write_cached_text(analysis_cache_dir, analysis_cache_key, analysis)
    return analysis
