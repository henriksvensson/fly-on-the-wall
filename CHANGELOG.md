# Changelog

All notable changes to Fly on the Wall are documented here.

## [0.5.0] - 2026-11-02

### Changed

- Obsidian filenames now include 24-hour recording time for chronological sorting and follow title or timestamp changes on republish, removing the old tracked file after the replacement is saved.

### Fixed

- Avoid overwriting other meetings or unrelated files when Obsidian filenames collide.

## [0.4.0] - 2026-07-02

### Added

- Added `fow service` commands for installing and managing the Linux systemd user watch service.
- Added a generated `service.env` placeholder for background service environment variables.

### Changed

- Made the Linux service install paths respect `XDG_CONFIG_HOME`.

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
