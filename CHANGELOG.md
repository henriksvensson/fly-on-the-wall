# Changelog

All notable changes to Fly on the Wall are documented here.

## [0.3.1] - 2026-06-15

### Fixed

- Fixed ElevenLabs keyterms encoding for glossary and known-person transcription hints.

## [0.3.0] - 2026-06-13

### Added

- Added glossary management with `fow glossary` commands.
- Added glossary and known-person hints for ElevenLabs transcription keyterms.
- Added glossary guidance to OpenAI cleanup, analysis, and title generation.
- Added Obsidian `participants` frontmatter links for known meeting speakers.

## [0.2.0] - 2026-06-09

### Added

- Added folder-level `--delete-originals-after-import` support for watched folders.
- Added `fow watch folders delete-originals-after-import` to toggle original cleanup for existing watch folders.
- Added a `py.typed` marker so editors and type checkers recognize the package as typed.
- Added pragmatic `basedpyright` type checking for source files and documented the code quality policy.

### Fixed

- Avoided a tight retry loop when the watch backend fails, such as `Too many open files`.
- Resolved source-level `basedpyright` warnings.

## [0.1.0] - 2026-06-09

### Added

- Initial public release of the `fow` CLI as the `fow-cli` PyPI package.
- Published GitHub repository and release artifacts.
