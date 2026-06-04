# Architecture Decisions

## Product Direction

- Build Fly on the Wall as a personal CLI note-taker for meeting audio.
- The consumer of the output is one user, not multiple tenants.
- Do not build login, accounts, hosted multi-tenancy, role management, or project workspaces.
- The application owns its internal storage layout. Users interact through CLI commands, immutable exports, and optional Obsidian publishing.

## Technology Stack

- Use Python 3.12+.
- Use Typer for the CLI command model.
- Use prompt-toolkit for richer interactive review controls.
- Use Rich for readable terminal output.
- Use SQLite for local metadata, state, indexing, pricing, usage, and pipeline progress.
- Use filesystem artifacts for large auditable data such as provider responses, cached LLM outputs, exports, and voice samples.
- Use httpx for provider HTTP calls.
- Use pyannote.audio, torch, and torchaudio for local speaker embeddings.
- Use uv for dependency and packaging workflow.
- Use pytest and Ruff for validation.

## Storage Model

- Use a local, single-user application store.
- SQLite is the operational source of truth for metadata and pipeline state.
- Files are used for large, auditable, and reproducible artifacts.
- Keep raw provider responses and derived artifacts rather than overwriting prior stages.
- Current locations:

```text
~/.local/share/fly-on-the-wall/
  fly.db
  audio/
  artifacts/
  voice-samples/
  exports/

~/.config/fly-on-the-wall/
  config.yaml
  glossary.yaml
```

## Configuration And Secrets

- Use one global application config, not project-specific config.
- Store non-secret defaults in config files:
  - default language
  - cleanup mode
  - glossary/domain terms
  - confidence thresholds
- API keys are read from environment variables first, then the OS keyring.
- Do not auto-load `.env` or `.envrc` files.
- Do not add app-owned plaintext secret files.
- Provide `fot secrets` commands for keyring management.

## CLI Model

- Keep the top-level CLI small and domain-oriented.
- Keep low-level operations available when they help automation.
- `fot process <audio>` is the main end-to-end command.
- Standalone `import` was removed because import without processing was not useful in normal use.
- Top-level `status` was moved to `fot meetings status`.
- Speaker review commands live under `fot meetings speakers` because speakers are meeting-local diarization labels.

Current command shape:

```bash
fot process <audio>
fot doctor

fot meetings list
fot meetings show <meeting>
fot meetings rename <meeting> "Title"
fot meetings remove <meeting>
fot meetings status <meeting>

fot meetings speakers unknown [--meeting <meeting>]
fot meetings speakers review [--meeting <meeting>]
fot meetings speakers assign <local-speaker-id> "Person A"
fot meetings speakers ignore <local-speaker-id>

fot people list
fot people create "Person A"
fot people show "Person A"
fot people set-user "Person A"
fot people show-user
fot people unset-user
fot people voice-samples "Person A"
fot people embeddings status
fot people embeddings backfill

fot refresh speakers [<meeting>] [--include-known-speakers]
fot refresh stale-meetings [--dry-run]
fot refresh meeting <meeting>

fot watch folders add <path> [--name <name>]
fot watch folders list
fot watch folders remove <id-or-name-or-path>
fot watch folders enable <id-or-name-or-path>
fot watch folders disable <id-or-name-or-path>
fot watch scan
fot watch run

fot publish targets add obsidian <path> --name <name> [--auto-publish]
fot publish targets list
fot publish targets remove <name-or-id>
fot publish targets enable <name-or-id>
fot publish targets disable <name-or-id>
fot publish meeting <meeting> --target <target>
fot publish all --target <target>

fot costs summary
fot costs meeting <meeting>

fot secrets status
fot secrets set <provider>
fot secrets remove <provider>
```

## Pipeline Model

- Use a SQLite-backed stage/state model instead of RabbitMQ, Celery, or another event system.
- Commands synchronously drive pending stages forward.
- Pipeline stages are resumable and idempotent where practical.
- If a run crashes, the database and artifacts show the last completed stage.
- Refresh commands reuse completed transcription and rerun derived stages.

Stage states:

```text
pending
running
failed
stale
skipped
```

Current pipeline:

```text
import audio into app storage
-> extract audio metadata and recording timestamp hints
-> assess obvious recording quality before transcription
-> transcribe and diarize with ElevenLabs
-> store raw provider response
-> normalize provider output into segments and local speakers
-> assess post-transcription recording quality
-> match local speakers to people using voice embeddings
-> render named transcript
-> deterministic transcript cleanup
-> optional OpenAI light cleanup
-> OpenAI meeting analysis
-> optional OpenAI generated title
-> immutable markdown export
-> optional auto-publish to enabled external targets
```

## Stage Output Ownership

- Each pipeline stage writes durable outputs owned by that stage.
- A stage must not mutate previous-stage artifacts.
- Raw provider responses remain unchanged.
- Normalized transcript data is derived from raw provider output.
- Cleaned transcript data is derived from rendered transcript data.
- Exports are immutable snapshots of selected stage outputs.
- Obsidian publishing is mutable and idempotent, separate from immutable internal exports.

## Provider Choices

- Transcription baseline: ElevenLabs Scribe v2.
- Transcript cleanup: OpenAI `gpt-5.4-mini`.
- Meeting analysis: OpenAI `gpt-5.4-mini`.
- Generated titles: OpenAI `gpt-5.4-mini`.
- Speaker identity: local pyannote-compatible embeddings.
- Provider-specific code adapts provider responses into normalized internal artifacts.
- Provider runs are first-class records so multiple providers or settings can be compared later.
- Provider-local speaker labels must never become stable identities.

## Audio Dependency

- FFmpeg and FFplay are explicit external runtime dependencies.
- Keep FFmpeg usage isolated behind the internal audio adapter.
- Current audio adapter operations include:
  - duration probing
  - metadata probing
  - conversion to WAV
  - clip extraction
  - normalization for embeddings
  - playback with interruption
- `fot doctor` checks runtime dependencies and embedding readiness.

## Core Data Model

Use these concepts in the database and code:

- `meeting`: one imported conversation or recording.
- `person`: stable human identity, such as Person A or Person B.
- `provider_run`: one transcription/diarization attempt by a provider/model/settings combination.
- `segment`: stable internal transcript segment derived from provider output.
- `local_speaker`: provider-local diarization label scoped to one provider run and meeting.
- `speaker_assignment`: current mapping from a local speaker to a person, uncertain match, unknown, or ignored.
- `voice_sample`: confirmed audio evidence for a person's voice identity.
- `local_speaker_embedding`: cached embedding for a meeting-local speaker.
- `correction`: first-class human correction or confirmation.
- `export`: immutable generated output snapshot.
- `publish_target`: mutable external publishing destination.
- `published_item`: mapping from one meeting to one mutable external note.
- `watch_folder` and `watch_item`: watched-folder ingestion state.
- `audio_metadata`: raw and normalized audio metadata.
- `recording_quality`: empty/nonsense/suspicious recording assessment.
- `service_price`: pricing snapshot for provider/model/service.
- `service_usage`: per-call usage and estimated cost.

Important relationships:

- A meeting has many provider runs.
- A provider run has many segments.
- A provider run has many local speakers.
- A person has many voice samples.
- A local speaker may have zero or one current speaker assignment.
- A local speaker has many segments.
- Corrections can create or update speaker assignments and voice samples.
- A meeting has many immutable exports.
- A meeting can have one mutable published item per publish target.

## Speaker Identity Model

- Stable identity is represented by `person`.
- Provider speaker labels are represented by `local_speaker` and are scoped to a meeting/provider run.
- Confirmed voice identity evidence is represented by `voice_sample`.
- Use `voice_sample`, not `profile_reference`, as the domain term.
- Voice samples may come from meeting time spans or standalone clips.
- Embeddings are cacheable derived data tied to model name/version.
- If the embedding model changes, old embeddings become stale rather than logically wrong.
- The system user is represented as a normal person with `people.is_user`.

## Speaker Matching

- Compare each local speaker embedding against multiple voice samples per person.
- Preserve manual user corrections during automatic speaker matching.
- Use confidence thresholds to produce known, uncertain, or unknown assignments.
- Mark downstream speaker-dependent stages stale only when assignments actually change.
- Default global speaker refresh targets meetings with unknown speakers.
- `--include-known-speakers` expands refresh to meetings whose speakers are already known.

## Meeting Speaker Review

- Unknown meeting speakers are local first, not global across meetings.
- Interactive review supports transcript examples and audio playback.
- Interactive controls use prompt-toolkit menus with arrow keys, Enter, shortcuts, and cancellation.
- Playback stays inside the menu and can be stopped with Enter.
- Review actions include:
  - assign with voice sample
  - assign only
  - new known person with voice sample
  - new known person only
  - ignore speaker forever
  - skip this time
  - quit review
- `skip this time` records no decision and the speaker may appear again.
- `ignore speaker forever` records an ignored speaker assignment and excludes it from future review.
- Final transcripts still render ignored speakers as unknown rather than exposing workflow labels.

## Corrections

- Human corrections are first-class records.
- Corrections should capture actions such as:
  - local speaker X in meeting Y is person Z
  - local speaker X should remain ignored
  - this audio span is a good voice sample for person Y
- Keep assignment history lightly rather than only storing the latest value.
- Corrections may create new people and new voice samples.

## Refresh And Staleness

- Adding a new person or voice sample should not automatically refresh all old meetings.
- Instead, refresh speaker matching explicitly and mark affected downstream stages stale only when assignments change.
- `fot refresh speakers` refreshes speaker matching.
- `fot refresh stale-meetings` refreshes meetings with stale derived stages.
- `fot refresh meeting <meeting>` refreshes one meeting's derived outputs without retranscription.
- Refresh should avoid expensive stages when cached artifacts are sufficient.

Examples:

- New voice samples can affect speaker matching, rendering, cleanup, analysis, export, and publishing.
- New glossary terms can affect cleanup, analysis, export, and publishing.
- New transcription provider settings do not invalidate old transcription unless manually requested.

## Post-Processing And Analysis

- Run cleanup before export by default.
- Split cleanup into deterministic cleanup and light LLM cleanup.
- OpenAI cleanup failures fall back to deterministic cleanup rather than blocking export.
- Meeting analysis is first-class and exported separately as `analysis.md`.
- Generated titles are applied only when the user has not manually set a title.

Deterministic cleanup:

- merge adjacent utterances from the same speaker
- normalize whitespace
- remove empty fragments
- preserve meaning

Light LLM cleanup:

- use OpenAI `gpt-5.4-mini`
- fix punctuation and casing
- lightly improve broken phrasing
- remove obvious filler without changing meaning
- preserve speaker names and order
- avoid summaries or invented details
- cache by model, prompt version, context, glossary, and transcript input

Analysis output sections:

- Summary
- Decisions
- Action Items
- Open Questions
- Important Details

## Glossary And Context

- Start with a global glossary file.
- Include known people, companies, products, and domain terms.
- Pass glossary and meeting-specific context into LLM cleanup.
- Meeting-specific context can include manual title, generated title, date, description, known participants, and topic notes.

## Export And Publishing Policy

- Internal exports are immutable snapshots.
- Do not overwrite prior internal exports.
- Export Markdown first.
- Current immutable export includes `transcript.md`, `analysis.md`, and `manifest.json`.
- Generated manuscript Markdown is output, not editable source of truth.
- Track export timestamp, input artifact references, and hashes where practical.
- External publishing is mutable and idempotent.
- Obsidian publishing stores the published path so title changes do not create duplicate notes.

## Watched Folders

- Watched folders are generic, not Dropbox-specific.
- Support local folders, rclone/FUSE mounts, and removable devices.
- Missing folders are skipped safely.
- Folders can be added before they exist.
- Event-driven watching is combined with periodic safety scans because cloud/removable mounts may not emit reliable events.
- Stable-file detection tolerates future mtimes from removable device clocks.
- Supported audio extensions currently include `.aac`, `.caf`, `.m4a`, `.mp3`, and `.wav`.
- Empty/nonsense/suspicious recordings can be ignored rather than fully processed.

## Cost Tracking

- Track provider pricing separately from provider usage.
- Store pricing snapshots in `service_prices`.
- Store per-call usage and estimated cost in `service_usage`.
- ElevenLabs usage is based on `audio_duration_secs` from raw responses.
- OpenAI usage is based on provider-reported token usage for future live calls.
- Historical OpenAI usage can only be approximated unless raw response usage was stored.
- Costs are estimates and should preserve the pricing snapshot used at calculation time.
- Use LiteLLM/OpenAI/ElevenLabs pricing data as seed data, with future refresh support possible.

## Meeting Identity

- Use an internal UUID for stable meeting identity.
- Also generate a readable slug for filenames, display, exports, and publishing.
- Original audio paths are preserved.
- Audio is copied into application-owned storage for reproducibility.
- Audio SHA-256 is used for deduplication.
- Manual titles are hard overrides.
- Generated titles do not currently change existing slugs/export paths.

## Failure Behavior

- Missing transcript should hard-fail the pipeline.
- Unknown speakers should not block rendering, cleanup, analysis, export, or publishing.
- Empty or nonsense recordings may be ignored.
- OpenAI cleanup failure falls back to deterministic cleanup.
- OpenAI analysis failure exports deterministic fallback analysis.
- Failed stages should be retryable.

## Testing Strategy

- Keep small fake or anonymized provider JSON fixtures in the repo.
- Test normalization, speaker mapping, rendering, cleanup boundaries, exports, publishing, costs, and pipeline state transitions.
- Avoid requiring live provider API calls for core tests.

## Deferred Decisions

- Final installation/distribution model.
- Exact confidence thresholds.
- Whether to add a formal pricing refresh command from LiteLLM.
- Whether to support a second diarization provider as a first-class production fallback.
- Whether normalized transcript segments should also be written as JSON artifacts in addition to SQLite.
- Whether to rewrite old private proof-of-concept history before making the repository public.
