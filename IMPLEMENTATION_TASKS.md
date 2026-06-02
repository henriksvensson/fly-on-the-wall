# Implementation Tasks

- [x] **Initialize Python project**
   Set up `uv`, package structure, Typer CLI entry point, formatting, and test dependencies.

- [x] **Add app configuration**
   Load global config from `~/.config/fly-on-the-wall/config.yaml` and API keys from environment variables.

- [x] **Create storage layout**
   Create application data directories under `~/.local/share/fly-on-the-wall/`.

- [x] **Add SQLite foundation**
   Create database connection, migrations/bootstrap, and initial tables for meetings, people, stages, and provider runs.

- [x] **Implement `fot doctor`**
   Check Python environment, FFmpeg availability, config paths, storage paths, and required API keys.

- [x] **Implement meeting import**
   Copy audio into app storage, create meeting record, generate UUID and readable slug.

- [x] **Build audio adapter**
   Wrap FFmpeg operations for duration checks, conversion, normalization, and clip extraction.

- [x] **Add pipeline stage runner**
   Track stage state in SQLite and run pending stages synchronously with resume/retry behavior.

- [x] **Implement ElevenLabs transcription provider**
   Upload audio, store raw provider response, and create a provider run record.

- [x] **Normalize transcript output**
    Convert provider responses into stable internal segments and local speakers.

- [x] **Render basic diarized transcript**
    Generate a readable transcript using provider-local speaker labels only.

- [x] **Add people commands**
    Implement `people list`, `people create`, and `people show`.

- [x] **Model voice samples**
    Store confirmed voice samples, source spans, extracted clips, and embedding metadata.

- [x] **Implement local speaker embeddings**
    Extract representative clips and cache embeddings for local speakers and voice samples.

- [ ] **Implement speaker matching**
    Compare local speakers against multiple voice samples per person and store confidence evidence.

- [ ] **Render named transcript**
    Replace local speaker labels with `Name`, `Name?`, or `Unknown` while preserving source labels.

- [ ] **Add deterministic cleanup**
    Merge adjacent same-speaker utterances, normalize whitespace, and remove empty fragments.

- [ ] **Add OpenAI light cleanup**
    Lightly improve punctuation, casing, and phrasing using glossary/context without changing meaning.

- [ ] **Implement immutable markdown export**
    Export cleaned named transcript and manifest without overwriting previous exports.

- [ ] **Implement `fot process`**
    Run import through export as one convenience command using the same stage runner.

- [ ] **Add meeting commands**
    Implement `meetings list`, `meetings show`, and `status`.

- [ ] **Add unknown speaker listing**
    Implement `speakers unknown` filtered globally or by meeting.

- [ ] **Add interactive speaker review**
    Show unknown speaker examples, optionally play clips, and support skip/assign/create-person actions.

- [ ] **Add speaker assignment commands**
    Implement `speakers assign` and `speakers create-person` with correction history.

- [ ] **Add reanalysis commands**
    Mark stale speaker-dependent stages and rerun `reanalyze speakers` or `reanalyze stale`.

- [ ] **Add glossary support**
    Load global glossary and pass known names/domain terms into cleanup.

- [ ] **Add golden fixture tests**
    Test provider normalization, rendering, cleanup, exports, and pipeline state transitions without live APIs.

- [ ] **Polish CLI output**
    Improve progress messages, errors, and next-step hints for normal daily use.
