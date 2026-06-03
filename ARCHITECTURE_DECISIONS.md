# Architecture Decisions

## Product Direction

- Build Fly on the Wall first as a personal CLI note-taker.
- The consumer of the output is one user, not multiple tenants.
- Do not build login, accounts, hosted multi-tenancy, or role management in the first version.
- The application owns its internal storage layout. Users interact through CLI commands and exports.

## Technology Stack

- Use Python 3.12+.
- Use Typer for the CLI.
- Use SQLite for local metadata, state, indexing, and pipeline progress.
- Use Pydantic for structured config and artifact schemas.
- Use httpx for provider HTTP calls.
- Use Rich for readable terminal output.
- Use uv for dependency and packaging workflow.
- Use pytest with small golden fixtures.

## Storage Model

- Use a local, single-user application store.
- SQLite is the operational source of truth for metadata and pipeline state.
- Files are used for large, auditable, and reproducible artifacts.
- Keep raw provider responses and derived artifacts rather than overwriting prior stages.
- Suggested locations:

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
- There is no separate project entity in v1.
- Store non-secret defaults in config files:
  - default transcription provider
  - language
  - export destination
  - confidence thresholds
  - cleanup mode
  - glossary/domain terms
- Use environment variables for API keys in v1.
- Do not build custom secret storage initially.

## CLI Model

- Provide composable stage commands for debugging and reprocessing.
- Provide one convenience command that runs the full pipeline from audio file to final markdown export.
- `process` should orchestrate the same stages as the individual commands, not use a separate hidden flow.
- Installation details can be decided later.

Initial command shape:

```bash
fot process recording.m4a --title "Intro call with Person B"
fot meetings list
fot meetings show <meeting-id>
fot people list
fot people create "Person B"
fot people show <person>
fot meetings speakers review --meeting <meeting-id>
fot meetings speakers unknown
fot meetings speakers assign <unknown-id> "Person B"
fot refresh speakers <meeting-id>
fot refresh stale-meetings
fot refresh meeting <meeting-id>
fot export <meeting-id>
fot meetings status <meeting-id>
fot doctor
```

## Pipeline Model

- Use a SQLite-backed stage/state model instead of RabbitMQ, Celery, or another event system.
- Commands synchronously drive pending stages forward.
- Pipeline stages are resumable and idempotent where practical.
- If a run crashes, the database and artifacts show the last completed stage.
- Old `running` stages should be recoverable as failed or interrupted.

Stage states:

```text
pending
running
done
failed
stale
skipped
```

Default v1 pipeline:

```text
import audio
-> normalize/check audio
-> transcribe and diarize
-> normalize provider output
-> extract/cache speaker evidence
-> match local speakers to people
-> render named transcript
-> deterministic transcript cleanup
-> light LLM transcript cleanup
-> immutable markdown export
```

## Stage Output Ownership

- Each pipeline stage writes durable outputs owned by that stage.
- A stage must not mutate previous-stage artifacts.
- Raw provider responses remain unchanged.
- Normalized transcript data is derived from raw provider output.
- Cleaned transcript data is derived from rendered transcript data.
- Exports are snapshots of selected stage outputs.

## Provider Modularity

- Treat transcription, diarization, speaker embedding, cleanup, and export as replaceable components.
- Provider-specific code should adapt provider responses into normalized internal artifacts.
- Provider runs must be first-class records so multiple providers or settings can be compared later.
- Do not let provider-local speaker labels become stable identities.

Initial provider choices:

- Transcription baseline: ElevenLabs.
- Secondary diarization: optional/manual initially, with Speechmatics available for comparison.
- Speaker identity: local embeddings.
- Transcript cleanup: fast/cheap OpenAI model.

## Audio Dependency

- FFmpeg is an explicit external runtime dependency.
- Do not try to replace FFmpeg in v1.
- Keep FFmpeg usage isolated behind an internal audio adapter.
- The audio adapter should expose application-level operations such as:
  - convert audio
  - extract clip
  - get duration
  - normalize for embedding
  - split long recordings if needed
- Add `fot doctor` to check for FFmpeg and other runtime dependencies.

## Core Data Model

Use these concepts in the database and code:

- `meeting`: one imported conversation or recording.
- `person`: stable human identity, such as Person A, Person C, or Person B.
- `provider_run`: one transcription/diarization attempt by a provider/model/settings combination.
- `segment`: stable internal transcript segment derived from provider output.
- `local_speaker`: provider-local diarization label scoped to one provider run and meeting.
- `speaker_assignment`: mapping from a local speaker or segment to a person, uncertain name, or unknown.
- `voice_sample`: confirmed audio evidence for a person's voice identity.
- `correction`: first-class human correction or confirmation.
- `export`: immutable generated output snapshot.

Important relationships:

- A meeting has many provider runs.
- A provider run has many segments.
- A provider run has many local speakers.
- A person has many voice samples.
- A local speaker may have zero or one current speaker assignment.
- A local speaker has many segments.
- Corrections can create or update speaker assignments and voice samples.

## Speaker Identity Model

- Stable identity is represented by `person`.
- Provider speaker labels are represented by `local_speaker` and are scoped to a meeting/provider run.
- Confirmed voice identity evidence is represented by `voice_sample`.
- Use `voice_sample`, not `profile_reference`, as the domain term.
- Voice samples may come from meeting time spans or standalone imported clips.
- V1 should focus on voice samples extracted from meeting spans.
- Embeddings are cacheable derived data tied to model name/version.
- If the embedding model changes, old embeddings become stale rather than logically wrong.

## Speaker Matching

- Do not rely on one averaged embedding per person.
- Compare against multiple voice samples per person.
- Track useful evidence such as:
  - best matching voice sample
  - top-k average score
  - mean score
  - number of samples
  - confidence margin versus next-best person
  - winning sample filename or ID
- Preserve uncertainty instead of hiding it.
- Use thresholds to produce `Name`, `Name?`, or `Unknown`.
- Detailed thresholds can be tuned later.

## Unknown Speaker Workflow

- Continue processing and exporting when speaker identity is uncertain.
- Unknown speakers are local first, not global across meetings.
- Add future support for merging unknowns across meetings only after confidence is good.
- Store unknown speaker evidence so it can be reviewed later.
- Interactive CLI review should support showing transcript examples and optionally playing audio snippets.
- Playback can use FFmpeg/ffplay, mpv, or another available local player.
- Playback is optional and should be dependency-checked by `fot doctor`.

Example review flow:

```text
Unknown speaker: unk_42
Meeting: Sales call
Total speech: 4m12s
Example:
  [00:05:12] "Ja, jag tycker att vi borde borja med..."

Options:
  p: play sample
  n: create new person
  a: assign to existing person
  s: skip
  u: keep unknown
```

## Corrections

- Human corrections are first-class records.
- Corrections should capture actions such as:
  - local speaker X in meeting Y is person Z
  - segment Z speaker should be person Y
  - this audio span is a good voice sample for person Y
- Keep assignment history lightly rather than only storing the latest value.
- Corrections may create new people and new voice samples.

## Refresh And Staleness

- Adding a new person or voice sample should not automatically reanalyze all old meetings.
- Instead, mark affected downstream stages as stale.
- Provide commands to refresh speaker matching, selected meetings, or stale meetings.
- Refresh should avoid expensive stages when cached artifacts are sufficient.

Examples:

- New voice sample invalidates speaker matching, rendering, cleanup, and export.
- New glossary terms invalidate cleanup and export.
- New transcription provider settings do not invalidate old transcription unless manually requested.

## Post-Processing

- Run cleanup before export by default.
- Split cleanup into deterministic cleanup and light LLM cleanup.

Deterministic cleanup:

- merge adjacent utterances from the same speaker
- normalize whitespace
- remove empty fragments
- preserve source timestamps and segment IDs where possible

Light LLM cleanup:

- use a fast/cheap OpenAI model initially
- fix punctuation and casing
- lightly improve broken phrasing
- correct known names and domain terms from glossary/context
- preserve speaker order and speaker names
- preserve meaning
- avoid summaries or invented details
- produce cleaned transcript text without overwriting normalized transcript text

Future cleanup modes may include conservative, balanced, aggressive, and summary/minutes modes.

## Glossary And Context

- Start with a global glossary file.
- Include known people, companies, products, and domain terms.
- Pass glossary and meeting-specific context into LLM cleanup.
- Meeting-specific context can include title, date, description, known participants, and topic notes.

## Export Policy

- Exports are immutable snapshots.
- Do not overwrite prior exports by default.
- Export markdown first in v1.
- Obsidian export is a likely first-class target.
- Generated markdown should be considered output, not the editable source of truth.
- Track export timestamp, version, input artifact references, and hashes where practical.

Suggested export shape:

```text
exports/
  obsidian/
    2026-06-02-topic-name/
      transcript.md
      manifest.json
```

Future exports may add:

- summary.md
- action-items.md
- decisions.md
- speaker-timeline.md

## Meeting Identity

- Use an internal UUID for stable meeting identity.
- Also generate a readable slug for filenames, display, and exports.
- Copy original audio into application-owned storage for reproducibility.

## Failure Behavior

- Missing transcript should hard-fail the pipeline.
- Unknown speakers should not block rendering or export.
- LLM cleanup failure may either fail export or allow deterministic-only export; exact v1 behavior can be decided during implementation.
- Failed stages should be retryable.

## Testing Strategy

- Keep small fake or anonymized provider JSON fixtures in the repo.
- Test normalization, speaker mapping, rendering, cleanup boundaries, and export formatting with golden files.
- Avoid requiring live provider API calls for core tests.

## Deferred Decisions

- Final installation/distribution model.
- Exact SQLite schema and migration tooling.
- Exact confidence thresholds.
- Exact OpenAI cleanup model.
- Whether embeddings live as SQLite blobs or sidecar files.
- Whether normalized transcript segments live only in SQLite or also as JSON artifacts. Current preference is both if not too costly.
- Whether LLM cleanup failure blocks export or falls back to deterministic cleanup.
