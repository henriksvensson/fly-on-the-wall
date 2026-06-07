# Fly on the Wall

[![PyPI](https://img.shields.io/pypi/v/fow-cli.svg)](https://pypi.org/project/fow-cli/)
[![Python Versions](https://img.shields.io/pypi/pyversions/fow-cli.svg)](https://pypi.org/project/fow-cli/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Fly on the Wall is a personal CLI note-taker for meeting audio.

It takes local audio recordings, transcribes them, identifies recurring speakers where possible, cleans the transcript, analyzes the meeting, exports durable Markdown artifacts, and can publish readable notes into an Obsidian vault.

The tool is designed for one person running it locally. There is no hosted service, login system, team workspace, or multi-tenant data model.

## Project Status

This is early alpha software. It is usable as a local personal CLI, but command behavior, storage schema, and output formats may still change between releases.

Until `1.0`, minor releases may include breaking changes. Back up `~/.local/share/fly-on-the-wall/` before upgrading if you depend on stored meeting data.

Issues and suggestions are welcome via GitHub Issues, but the project is provided as-is with no support guarantee.

Audio is sent to configured transcription/AI providers during processing. Optional speaker identity embeddings run locally when installed with the `identity` extra. External providers may charge usage-based fees depending on your provider account, pricing plan, and processing volume.

## Development Transparency

This project was developed as an agentic coding project using [OpenCode](https://opencode.ai/) with [OpenAI](https://openai.com/) GPT-5.5. Code quality checks were supported by CodeScene's [CodeHealth](https://codescene.com/product/code-health) analysis.

## What It Does

`fow process <audio>` runs the main pipeline:

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

- `transcript.md`: cleaned readable manuscript.
- `analysis.md`: summary, decisions, action items, open questions, and important details.
- `manifest.json`: internal metadata about the export.

## Current Provider Setup

The current transcription provider is ElevenLabs Scribe v2.

OpenAI is used for optional transcript cleanup, meeting analysis, and generated meeting titles when an OpenAI API key is available.

Speaker identity matching uses local embeddings via `pyannote.audio` / `pyannote/wespeaker-voxceleb-resnet34-LM`. Audio used for identity matching is processed locally. The first model load may contact Hugging Face to download model weights unless they are already cached locally.

## Installation

Install the CLI with `uv tool`:

```bash
uv tool install fow-cli
fow setup
```

Speaker identity matching is optional and adds heavier local ML dependencies:

```bash
uv tool install "fow-cli[identity]"
```

If you already installed the base CLI with `uv tool`, upgrade it with the optional extra:

```bash
uv tool upgrade --reinstall "fow-cli[identity]"
```

Development from a source checkout also uses `uv`:

```bash
uv sync
uv run fow
```

Include speaker identity dependencies during local development with:

```bash
uv sync --extra identity
```

You can point `fow` at `uv run fow` with a shell alias:

```bash
alias fow="uv run fow"
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
fow secrets status
fow secrets set elevenlabs
fow secrets set openai
fow secrets remove openai
```

Expected environment variables:

```text
ELEVENLABS_API_KEY
OPENAI_API_KEY
```

## Basic Usage

Run the interactive setup wizard:

```bash
fow setup
```

It checks required dependencies, helps store API keys, sets your user identity, and can configure Obsidian publishing and watched folders.

Process one recording:

```bash
fow process path/to/meeting.m4a
```

Optionally provide a manual title and context:

```bash
fow process path/to/meeting.m4a --title "Board prep" --description "Monthly board preparation call"
```

List meetings:

```bash
fow meetings list
```

Show one meeting:

```bash
fow meetings show <meeting>
```

Show pipeline status:

```bash
fow meetings status <meeting>
```

Refresh derived outputs for one meeting without retranscribing:

```bash
fow refresh meeting <meeting>
```

Refresh every meeting with stale derived outputs:

```bash
fow refresh stale-meetings
```

## People And Speakers

The CLI uses two related concepts:

- A **person** is a stable real-world identity, such as `Person A` or `Person B`.
- A **meeting speaker** is a local diarization label inside one provider run, such as `speaker_0`.

Manage known people:

```bash
fow people list
fow people create "Person A"
fow people show "Person A"
```

Review unknown meeting speakers interactively:

```bash
fow meetings speakers review
fow meetings speakers review --include-uncertain
fow meetings speakers review --only-uncertain
```

Review speakers for one meeting:

```bash
fow meetings speakers review --meeting <meeting>
```

List meeting speakers that are not assigned to known people:

```bash
fow meetings speakers unknown
fow meetings speakers unknown --meeting <meeting>
```

Assign a meeting speaker to a known person, creating the person if needed:

```bash
fow meetings speakers assign <local-speaker-id> "Person A"
```

Ignore a meeting speaker so it does not appear in future reviews:

```bash
fow meetings speakers ignore <local-speaker-id>
```

Refresh speaker matching after adding voice samples or changing identities:

```bash
fow refresh speakers
fow refresh speakers <meeting>
fow refresh speakers --include-known-speakers
```

Backfill missing known-person voice embeddings:

```bash
fow people embeddings status
fow people embeddings backfill
```

## Watched Folders

Fly on the Wall can watch local folders, mounted Dropbox/rclone folders, and removable recorder folders.

Add a folder:

```bash
fow watch folders add /path/to/recordings --name recordings
```

List watched folders:

```bash
fow watch folders list
```

Run one scan:

```bash
fow watch scan
```

Watch continuously:

```bash
fow watch run
```

The watcher tolerates missing/remounted folders and uses periodic scans because cloud/removable mounts may not emit reliable filesystem events.

## Publishing To Obsidian

Publishing is separate from internal exports.

Internal exports are immutable. Obsidian notes are mutable and idempotent, so republishing updates the existing note rather than creating duplicate notes.

Add an Obsidian target:

```bash
fow publish targets add obsidian "/path/to/Obsidian Vault/Fly on the Wall" --name obsidian --auto-publish
```

Publish one meeting:

```bash
fow publish meeting <meeting> --target obsidian
```

Publish all exported meetings:

```bash
fow publish all --target obsidian
```

## Example Personal Setup

One practical setup is to combine several recording sources with watched folders and Obsidian publishing:

- A Philips DVT 4110 voice recorder is automounted when connected, exposing recordings as a local folder.
- A dedicated Dropbox recording folder is synced locally with [rclone](https://rclone.org/dropbox/).
- On iPhone, [RecUp](https://apps.apple.com/us/app/recup-record-to-the-cloud/id416288287) can upload recordings directly to Dropbox. Assigning RecUp to the iPhone Action Button makes quick capture a one-button workflow.
- `fow watch run` watches both the recorder mount and the local Dropbox/rclone folder.
- Processed notes are published into an Obsidian vault. If the vault is already synced with [Remotely Save](https://github.com/remotely-save/remotely-save), notes can then appear on other devices through Obsidian sync tooling.

In that setup, recordings can enter from either the hardware recorder or phone uploads, `fow` processes them locally, and Obsidian becomes the final reading and review surface.

## Cost Tracking

The app records estimated external service usage and costs for future live provider calls.

It tracks:

- ElevenLabs transcription usage via `audio_duration_secs`.
- OpenAI cleanup, analysis, and title-generation usage via provider token usage.
- Pricing snapshots used for each estimate.

Show total estimated costs:

```bash
fow costs summary
```

Show estimated costs for one meeting:

```bash
fow costs meeting <meeting>
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

## Uninstalling

Remove the installed CLI:

```bash
uv tool uninstall fow-cli
```

Remove local configuration and app data if you no longer need stored meetings, exports, raw provider responses, voice samples, or settings:

```bash
rm -rf ~/.config/fly-on-the-wall ~/.local/share/fly-on-the-wall
```

This does not remove original recordings that were processed from outside the app storage directory.

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

Build distribution artifacts:

```bash
uv build
```

Test a built wheel locally:

```bash
uv tool install dist/fow_cli-0.1.0-py3-none-any.whl
fow setup
```

Publish to PyPI after verifying the build, package name, and license metadata:

```bash
uv publish
```

## Support

If Fly on the Wall is useful to you, and you have the spare cash, buying me a coffee would be lovely. Absolutely no pressure.

[![Buy Me A Coffee](https://img.buymeacoffee.com/button-api/?text=Buy%20me%20a%20coffee&emoji=&slug=henriksvensson&button_colour=FFDD00&font_colour=000000&font_family=Lato&outline_colour=000000&coffee_colour=ffffff)](https://buymeacoffee.com/henriksvensson)
