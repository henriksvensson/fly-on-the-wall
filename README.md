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

Run tests:

```bash
uv run pytest
```

Run lint:

```bash
uv run ruff check .
```

Architecture notes live in:

```text
ARCHITECTURE_DECISIONS.md
```

Implementation tasks live in:

```text
IMPLEMENTATION_TASKS.md
```

Original proof-of-concept scripts and detailed notes live in:

```text
poc/
```

## Proof-Of-Concept Results

The first experiments focused on Swedish meeting audio, transcription quality, diarization quality, and whether stable speaker identity could be recovered across recordings.

### Transcription And Diarization Providers

ElevenLabs Scribe v2 became the main baseline. It produced the best overall combination of readable Swedish transcription, coherent meeting context, and useful diarization. It was not perfect: in one important meeting it merged two recurring speakers into one diarization label. The conclusion was that ElevenLabs is strong for transcript content, but speaker separation still needs review and correction.

Speechmatics was the diarization runner-up. Default-ish settings also merged the same recurring speakers, but higher speaker sensitivity over-split the meeting and separated some speakers that ElevenLabs merged. This made Speechmatics useful as a possible second diarization pass or diagnostic comparison, even though it was not selected as the main provider.

Soniox produced strong wording on one early sample and was one of the better providers for transcription quality, but ElevenLabs and Speechmatics were stronger for speaker continuity in the tested workflow.

Gladia produced usable diarization, but wording was weaker than the strongest providers.

Deepgram was weaker on Swedish wording in early tests.

OpenAI transcription was weaker on the tested Swedish clip. One diarized model hallucinated English, making it a poor fit for this specific transcription use case.

Bee was not useful for this workflow. It identified one known speaker in some places, but most speakers remained `Unknown`, and transcript content was significantly weaker than ElevenLabs and Speechmatics on the tested Swedish meeting.

Current provider ranking for this use case:

1. ElevenLabs: best overall readable transcript and decent diarization.
2. Speechmatics: useful diarization runner-up, especially with sensitivity tuning.
3. Soniox: strong wording, less useful for speaker continuity.
4. Gladia: usable but weaker wording.
5. Deepgram, OpenAI transcription, Bee: weaker for the tested Swedish meeting scenario.

### Speaker Identity

Provider diarization labels are local to one recording. `speaker_1` in one meeting is not the same identity as `speaker_1` in another meeting.

The speaker identity proof of concept used local voice embeddings from:

```text
pyannote/wespeaker-voxceleb-resnet34-LM
```

This model worked locally without requiring gated Hugging Face access.

On the sample test, same-speaker scores were much higher than cross-speaker scores:

```text
speaker_0 -> speaker_0: 0.4721
speaker_1 -> speaker_1: 0.7921
speaker_2 -> speaker_2: 0.6278
cross-speaker scores: roughly 0.0250 to 0.1594
```

The conclusion was that local embeddings are good enough to support recurring-speaker identity matching, especially when combined with human-confirmed voice samples.

### Speaker Matching Lessons

Using one averaged embedding per person can be brittle. In one test, adding a better voice sample for one known speaker improved matching significantly:

- Before adding the better profile clip, one match scored around `0.638`.
- After adding a longer confirmed voice sample, it improved to around `0.767`.
- Using only the new voice sample in a temporary test improved it further to around `0.851`.

The lesson was that multiple voice samples should be preserved and compared, not blindly averaged into one canonical voice profile.

### Product Direction From The PoC

The core product insight from the proof of concepts is that transcription, diarization, speaker identity, and readability are separate problems.

Fly on the Wall treats them as separate pipeline stages so each one can be inspected, corrected, cached, and improved independently.
