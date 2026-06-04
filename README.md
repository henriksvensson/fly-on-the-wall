# Fly on the Wall

Fly on the Wall is a personal CLI note-taker for meeting audio.

It takes local audio recordings, transcribes them, identifies recurring speakers where possible, cleans the transcript, analyzes the meeting, exports durable Markdown artifacts, and can publish readable notes into an Obsidian vault.

The tool is designed for one person running it locally. There is no hosted service, login system, team workspace, or multi-tenant data model.

## What It Does

`fot process <audio>` runs the main pipeline:

1. Imports the audio into local app storage.
2. Extracts audio metadata and recording timestamps where possible.
3. Sends the raw audio to ElevenLabs for transcription and diarization.
4. Stores the raw provider response for auditability.
5. Normalizes provider output into internal segments and meeting-local speakers.
6. Matches meeting-local speakers to known people using local voice embeddings.
7. Renders a named transcript.
8. Runs deterministic cleanup.
9. Optionally runs OpenAI light cleanup, meeting analysis, and title generation.
10. Exports immutable Markdown artifacts.
11. Publishes to configured Obsidian targets if auto-publish is enabled.

Final user-facing exports include:

- `transcript.md`: cleaned readable transcript.
- `analysis.md`: summary, decisions, action items, open questions, and important details.
- `manifest.json`: internal metadata about the export.

## Current Provider Setup

The current transcription provider is ElevenLabs Scribe v2.

OpenAI is used for optional transcript cleanup, meeting analysis, and generated meeting titles when an OpenAI API key is available.

Speaker identity matching uses local embeddings via `pyannote.audio` / `pyannote/wespeaker-voxceleb-resnet34-LM`. Audio used for identity matching is processed locally. The first model load may contact Hugging Face to download model weights unless they are already cached locally.

## Installation

This project uses `uv`.

```bash
uv sync
uv run fot
```

You can point `fot` at `uv run fot` with a shell alias:

```bash
alias fot="uv run fot"
```

## Configuration And Secrets

Configuration lives under:

```text
~/.config/fly-on-the-wall/
```

Application data lives under:

```text
~/.local/share/fly-on-the-wall/
```

API keys are read from environment variables first, then from the OS keyring.

Useful secret commands:

```bash
fot secrets status
fot secrets set elevenlabs
fot secrets set openai
fot secrets remove openai
```

Expected environment variables:

```text
ELEVENLABS_API_KEY
OPENAI_API_KEY
```

## Basic Usage

Process one recording:

```bash
fot process path/to/meeting.m4a
```

Optionally provide a manual title and context:

```bash
fot process path/to/meeting.m4a --title "Board prep" --description "Monthly board preparation call"
```

List meetings:

```bash
fot meetings list
```

Show one meeting:

```bash
fot meetings show <meeting>
```

Show pipeline status:

```bash
fot meetings status <meeting>
```

Refresh derived outputs for one meeting without retranscribing:

```bash
fot refresh meeting <meeting>
```

Refresh every meeting with stale derived outputs:

```bash
fot refresh stale-meetings
```

## People And Speakers

The CLI uses two related concepts:

- A **person** is a stable real-world identity, such as `Person A` or `Person B`.
- A **meeting speaker** is a local diarization label inside one provider run, such as `speaker_0`.

Manage known people:

```bash
fot people list
fot people create "Person A"
fot people show "Person A"
```

Review unknown meeting speakers interactively:

```bash
fot meetings speakers review
```

Review speakers for one meeting:

```bash
fot meetings speakers review --meeting <meeting>
```

List meeting speakers that are not assigned to known people:

```bash
fot meetings speakers unknown
fot meetings speakers unknown --meeting <meeting>
```

Assign a meeting speaker to a known person, creating the person if needed:

```bash
fot meetings speakers assign <local-speaker-id> "Person A"
```

Ignore a meeting speaker so it does not appear in future reviews:

```bash
fot meetings speakers ignore <local-speaker-id>
```

Refresh speaker matching after adding voice samples or changing identities:

```bash
fot refresh speakers
fot refresh speakers <meeting>
fot refresh speakers --include-known-speakers
```

Backfill missing known-person voice embeddings:

```bash
fot people embeddings status
fot people embeddings backfill
```

## Watched Folders

Fly on the Wall can watch local folders, mounted Dropbox/rclone folders, and removable recorder folders.

Add a folder:

```bash
fot watch folders add /path/to/recordings --name recordings
```

List watched folders:

```bash
fot watch folders list
```

Run one scan:

```bash
fot watch scan
```

Watch continuously:

```bash
fot watch run
```

The watcher tolerates missing/remounted folders and uses periodic scans because cloud/removable mounts may not emit reliable filesystem events.

## Publishing To Obsidian

Publishing is separate from internal exports.

Internal exports are immutable. Obsidian notes are mutable and idempotent, so republishing updates the existing note rather than creating duplicate notes.

Add an Obsidian target:

```bash
fot publish targets add obsidian "/path/to/Obsidian Vault/Fly on the Wall" --name obsidian --auto-publish
```

Publish one meeting:

```bash
fot publish meeting <meeting> --target obsidian
```

Publish all exported meetings:

```bash
fot publish all --target obsidian
```

## Cost Tracking

The app records estimated external service usage and costs for future live provider calls.

It tracks:

- ElevenLabs transcription usage via `audio_duration_secs`.
- OpenAI cleanup, analysis, and title-generation usage via provider token usage.
- Pricing snapshots used for each estimate.

Show total estimated costs:

```bash
fot costs summary
```

Show estimated costs for one meeting:

```bash
fot costs meeting <meeting>
```

Historical ElevenLabs usage can be backfilled accurately from stored raw responses. Historical OpenAI usage can only be approximated unless raw OpenAI response usage was stored.

## Local Storage

The app stores operational state in SQLite and large artifacts on disk:

```text
~/.local/share/fly-on-the-wall/
  fly.db
  audio/
  artifacts/
  voice-samples/
  exports/
```

Raw provider responses are intentionally preserved. They are useful for debugging, normalization changes, speaker review, cost tracking, and future reprocessing.

## Development

Install development dependencies:

```bash
uv sync --dev
```

Install pre-commit hooks:

```bash
uv run pre-commit install
```

Run all pre-commit hooks manually:

```bash
uv run pre-commit run --all-files
```

Run tests:

```bash
uv run pytest
```

Run lint and formatting checks:

```bash
uv run ruff check .
uv run ruff format --check .
```

Architecture notes live in:

```text
ARCHITECTURE_DECISIONS.md
```

Implementation tasks live in:

```text
IMPLEMENTATION_TASKS.md
```

Detailed proof-of-concept results live in:

```text
PROOF_OF_CONCEPT_RESULTS.md
```

Original proof-of-concept scripts live in:

```text
poc/
```

## Proof-Of-Concept Results

Detailed anonymized proof-of-concept notes live in [`PROOF_OF_CONCEPT_RESULTS.md`](PROOF_OF_CONCEPT_RESULTS.md).

The main choices that came out of the proof of concept were:

- ElevenLabs Scribe v2 is the current default transcription provider because it gave the best overall balance of readable Swedish transcription and useful diarization.
- Speechmatics was useful as a diarization comparison point, especially when sensitivity tuning over-split speakers that ElevenLabs merged.
- Local speaker embeddings were promising enough to support recurring-speaker identity matching across recordings.
- Human-confirmed voice samples materially improved speaker matching quality.
- Transcription, diarization, speaker identity, and transcript readability should remain separate pipeline stages so each can be inspected and improved independently.
