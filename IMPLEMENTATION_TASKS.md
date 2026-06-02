# Implementation Tasks

1. **Initialize Python project**
   Set up `uv`, package structure, Typer CLI entry point, formatting, and test dependencies.

2. **Add app configuration**
   Load global config from `~/.config/fly-on-the-wall/config.yaml` and API keys from environment variables.

3. **Create storage layout**
   Create application data directories under `~/.local/share/fly-on-the-wall/`.

4. **Add SQLite foundation**
   Create database connection, migrations/bootstrap, and initial tables for meetings, people, stages, and provider runs.

5. **Implement `fot doctor`**
   Check Python environment, FFmpeg availability, config paths, storage paths, and required API keys.

6. **Implement meeting import**
   Copy audio into app storage, create meeting record, generate UUID and readable slug.

7. **Build audio adapter**
   Wrap FFmpeg operations for duration checks, conversion, normalization, and clip extraction.

8. **Add pipeline stage runner**
   Track stage state in SQLite and run pending stages synchronously with resume/retry behavior.

9. **Implement ElevenLabs transcription provider**
   Upload audio, store raw provider response, and create a provider run record.

10. **Normalize transcript output**
    Convert provider responses into stable internal segments and local speakers.

11. **Render basic diarized transcript**
    Generate a readable transcript using provider-local speaker labels only.

12. **Add people commands**
    Implement `people list`, `people create`, and `people show`.

13. **Model voice samples**
    Store confirmed voice samples, source spans, extracted clips, and embedding metadata.

14. **Implement local speaker embeddings**
    Extract representative clips and cache embeddings for local speakers and voice samples.

15. **Implement speaker matching**
    Compare local speakers against multiple voice samples per person and store confidence evidence.

16. **Render named transcript**
    Replace local speaker labels with `Name`, `Name?`, or `Unknown` while preserving source labels.

17. **Add deterministic cleanup**
    Merge adjacent same-speaker utterances, normalize whitespace, and remove empty fragments.

18. **Add OpenAI light cleanup**
    Lightly improve punctuation, casing, and phrasing using glossary/context without changing meaning.

19. **Implement immutable markdown export**
    Export cleaned named transcript and manifest without overwriting previous exports.

20. **Implement `fot process`**
    Run import through export as one convenience command using the same stage runner.

21. **Add meeting commands**
    Implement `meetings list`, `meetings show`, and `status`.

22. **Add unknown speaker listing**
    Implement `speakers unknown` filtered globally or by meeting.

23. **Add interactive speaker review**
    Show unknown speaker examples, optionally play clips, and support skip/assign/create-person actions.

24. **Add speaker assignment commands**
    Implement `speakers assign` and `speakers create-person` with correction history.

25. **Add reanalysis commands**
    Mark stale speaker-dependent stages and rerun `reanalyze speakers` or `reanalyze stale`.

26. **Add glossary support**
    Load global glossary and pass known names/domain terms into cleanup.

27. **Add golden fixture tests**
    Test provider normalization, rendering, cleanup, exports, and pipeline state transitions without live APIs.

28. **Polish CLI output**
    Improve progress messages, errors, and next-step hints for normal daily use.
