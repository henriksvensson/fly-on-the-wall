from __future__ import annotations

from pathlib import Path
from time import sleep
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table
from watchfiles import watch

from fly_on_the_wall import __version__
from fly_on_the_wall.audio import AudioError, play_audio
from fly_on_the_wall.config import load_config
from fly_on_the_wall.db import database
from fly_on_the_wall.doctor import has_failures, run_checks
from fly_on_the_wall.embeddings import EmbeddingBackend, PyannoteEmbeddingBackend
from fly_on_the_wall.meetings import (
    delete_meeting,
    get_meeting,
    import_meeting,
    list_meetings,
    meeting_stage_status,
    rename_meeting,
)
from fly_on_the_wall.people import (
    Person,
    create_person,
    get_person,
    get_user_person,
    list_people,
    set_user_person,
    unset_user_person,
)
from fly_on_the_wall.processing import process_audio, refresh_meeting
from fly_on_the_wall.publishing import (
    add_publish_target,
    list_publish_targets,
    publish_all_meetings,
    publish_meeting,
    remove_publish_target,
    set_publish_target_enabled,
)
from fly_on_the_wall.reanalysis import (
    list_stale_stages,
    mark_speaker_reanalysis_stale,
    rerun_speaker_matching,
)
from fly_on_the_wall.recording_quality import RecordingIgnoredError
from fly_on_the_wall.secrets import (
    SecretError,
    get_api_key_status,
    known_providers,
    remove_api_key,
    set_api_key,
)
from fly_on_the_wall.speaker_identity import (
    create_voice_identity_from_speaker,
    mark_unknown,
    prepare_speaker_review_clip,
)
from fly_on_the_wall.speakers import (
    assign_speaker_to_person,
    create_person_from_speaker,
    list_unknown_speakers,
    speaker_examples,
)
from fly_on_the_wall.voice_samples import list_voice_samples
from fly_on_the_wall.watch import (
    DEFAULT_STABLE_AGE_SECONDS,
    add_watch_folder,
    list_watch_folders,
    remove_watch_folder,
    scan_watch_folders,
    set_watch_folder_enabled,
)

app = typer.Typer(
    name="fot",
    help="Personal CLI note-taker for meeting audio.",
    no_args_is_help=True,
)
people_app = typer.Typer(help="Manage known people.", no_args_is_help=True)
meetings_app = typer.Typer(help="Inspect meetings.", no_args_is_help=True)
speakers_app = typer.Typer(help="Review and assign speakers.", no_args_is_help=True)
reanalyze_app = typer.Typer(help="Mark and inspect stale analysis.", no_args_is_help=True)
secrets_app = typer.Typer(help="Manage API keys in the OS keyring.", no_args_is_help=True)
watch_app = typer.Typer(help="Process audio from watched folders.", no_args_is_help=True)
watch_folders_app = typer.Typer(help="Manage watched folders.", no_args_is_help=True)
publish_app = typer.Typer(help="Publish meetings to external targets.", no_args_is_help=True)
publish_targets_app = typer.Typer(help="Manage publish targets.", no_args_is_help=True)
app.add_typer(people_app, name="people")
app.add_typer(meetings_app, name="meetings")
app.add_typer(speakers_app, name="speakers")
app.add_typer(reanalyze_app, name="reanalyze")
app.add_typer(secrets_app, name="secrets")
app.add_typer(watch_app, name="watch")
watch_app.add_typer(watch_folders_app, name="folders")
app.add_typer(publish_app, name="publish")
publish_app.add_typer(publish_targets_app, name="targets")
console = Console()


def _version_callback(show_version: bool) -> None:
    if show_version:
        console.print(f"fly-on-the-wall {__version__}")
        raise typer.Exit


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show the application version.",
    ),
) -> None:
    """Run Fly on the Wall commands."""


@app.command()
def hello() -> None:
    """Verify that the CLI is installed and runnable."""
    console.print("Fly on the Wall CLI is ready.")


@app.command()
def doctor() -> None:
    """Check local runtime configuration and dependencies."""
    checks = run_checks()
    table = Table(title="Fly on the Wall Doctor")
    table.add_column("Check")
    table.add_column("Status")
    table.add_column("Detail")

    for check in checks:
        table.add_row(check.name, "ok" if check.ok else "missing", check.detail)

    console.print(table)
    if has_failures(checks):
        raise typer.Exit(code=1)


@app.command("import")
def import_audio(
    audio_path: Annotated[Path, typer.Argument(exists=True, file_okay=True, dir_okay=False)],
    title: Annotated[
        str | None, typer.Option("--title", "-t", help="Manual meeting title override.")
    ] = None,
    description: Annotated[
        str | None, typer.Option("--description", "-d", help="Meeting context.")
    ] = None,
) -> None:
    """Import an audio file into application storage."""
    config = load_config()
    with database() as connection:
        meeting = import_meeting(connection, audio_path, title, config, description=description)

    console.print(f"Imported meeting {meeting.slug}")
    console.print(f"Title: {meeting.title}")
    console.print(f"ID: {meeting.id}")
    console.print(f"Audio: {meeting.imported_audio_path}")
    console.print(f"Next: fot process {audio_path}")


@app.command()
def process(
    audio_path: Annotated[Path, typer.Argument(exists=True, file_okay=True, dir_okay=False)],
    title: Annotated[
        str | None, typer.Option("--title", "-t", help="Manual meeting title override.")
    ] = None,
    description: Annotated[
        str | None, typer.Option("--description", "-d", help="Meeting context.")
    ] = None,
) -> None:
    """Process audio from import through markdown export."""
    config = load_config()
    with database() as connection:
        try:
            result = process_audio(
                connection,
                audio_path,
                title,
                config,
                description=description,
                progress=lambda message: console.print(f"-> {message}"),
            )
        except RecordingIgnoredError as exc:
            console.print(f"Ignored recording {exc.meeting.slug}: {exc.quality.reason}")
            return

    console.print(f"Processed meeting {result.meeting.slug}")
    console.print(f"Transcript: {result.export.transcript_path}")
    console.print(f"Analysis: {result.export.analysis_path}")
    console.print(f"Review unknown speakers: fot speakers unknown --meeting {result.meeting.slug}")


@watch_app.command("scan")
def watch_scan(
    stable_age_seconds: Annotated[
        int,
        typer.Option(
            "--stable-age-seconds",
            min=0,
            help="Only process files unchanged for at least this many seconds.",
        ),
    ] = DEFAULT_STABLE_AGE_SECONDS,
) -> None:
    """Scan enabled watched folders once and process new audio files."""
    config = load_config()
    _scan_watch_once(config, stable_age_seconds)


@watch_app.command("run")
def watch_run(
    interval_seconds: Annotated[
        int,
        typer.Option("--interval-seconds", min=1, help="Seconds between safety scans."),
    ] = 60,
    stable_age_seconds: Annotated[
        int,
        typer.Option(
            "--stable-age-seconds",
            min=0,
            help="Only process files unchanged for at least this many seconds.",
        ),
    ] = DEFAULT_STABLE_AGE_SECONDS,
) -> None:
    """Watch enabled folders and process new audio files as they appear."""
    config = load_config()
    with database() as connection:
        folders = [folder for folder in list_watch_folders(connection) if folder.enabled]

    if not folders:
        console.print("No enabled watch folders configured.")
        console.print("Add one with: fot watch folders add <path>")
        raise typer.Exit(code=1)

    console.print("Watching folders for audio changes. Press Ctrl+C to stop.")
    for path in [folder.path for folder in folders]:
        console.print(f"- {path}")

    _scan_watch_once(config, stable_age_seconds)
    while True:
        with database() as connection:
            folders = [folder for folder in list_watch_folders(connection) if folder.enabled]

        existing_paths = [folder.path for folder in folders if folder.path.is_dir()]
        if not existing_paths:
            console.print("No watched folders are currently mounted. Running safety scan.")
            _scan_watch_once(config, stable_age_seconds)
            sleep(interval_seconds)
            continue

        try:
            changes = next(
                watch(
                    *existing_paths,
                    recursive=True,
                    yield_on_timeout=True,
                    rust_timeout=interval_seconds * 1000,
                )
            )
        except (OSError, RuntimeError) as exc:
            console.print(f"Watch backend restarted after folder change: {exc}")
            _scan_watch_once(config, stable_age_seconds)
            continue

        if changes:
            console.print(f"Detected {len(changes)} file change(s).")
        else:
            console.print("Running periodic safety scan.")
        _scan_watch_once(config, stable_age_seconds)


@watch_folders_app.command("add")
def watch_folders_add(
    path: Annotated[Path, typer.Argument(file_okay=False, dir_okay=True)],
    name: Annotated[str | None, typer.Option("--name", "-n", help="Optional folder name.")] = None,
) -> None:
    """Add a folder to scan for audio files."""
    with database() as connection:
        try:
            folder = add_watch_folder(connection, path, name)
        except Exception as exc:
            console.print(str(exc))
            raise typer.Exit(code=1) from exc
    console.print(f"Added watch folder {folder.path}")
    if folder.name:
        console.print(f"Name: {folder.name}")


@watch_folders_app.command("list")
def watch_folders_list() -> None:
    """List watched folders."""
    with database() as connection:
        folders = list_watch_folders(connection)
    if not folders:
        console.print("No watch folders configured.")
        return
    table = Table(title="Watch Folders")
    table.add_column("ID")
    table.add_column("Name")
    table.add_column("Enabled")
    table.add_column("Path")
    for folder in folders:
        table.add_row(
            folder.id,
            folder.name or "",
            "yes" if folder.enabled else "no",
            str(folder.path),
        )
    console.print(table)


@watch_folders_app.command("remove")
def watch_folders_remove(identifier: str) -> None:
    """Remove a watched folder by id, name, or path."""
    with database() as connection:
        folder = remove_watch_folder(connection, identifier)
    if folder is None:
        console.print(f"Watch folder not found: {identifier}")
        raise typer.Exit(code=1)
    console.print(f"Removed watch folder {folder.path}")


@watch_folders_app.command("enable")
def watch_folders_enable(identifier: str) -> None:
    """Enable a watched folder by id, name, or path."""
    _set_watch_folder_enabled_command(identifier, True)


@watch_folders_app.command("disable")
def watch_folders_disable(identifier: str) -> None:
    """Disable a watched folder by id, name, or path."""
    _set_watch_folder_enabled_command(identifier, False)


@publish_app.command("meeting")
def publish_meeting_command(
    meeting: str,
    target: Annotated[str, typer.Option("--target", "-t", help="Publish target name or id.")],
) -> None:
    """Publish one meeting to a configured target."""
    with database() as connection:
        try:
            result = publish_meeting(connection, meeting, target)
        except ValueError as exc:
            console.print(str(exc))
            raise typer.Exit(code=1) from exc
    console.print(f"Published {meeting} to {result.target.name}")
    console.print(f"Output: {result.output_path}")


@publish_app.command("all")
def publish_all_command(
    target: Annotated[str, typer.Option("--target", "-t", help="Publish target name or id.")],
    only_unpublished: Annotated[
        bool,
        typer.Option("--only-unpublished", help="Skip meetings already published to this target."),
    ] = False,
) -> None:
    """Publish all exported meetings to a configured target."""
    with database() as connection:
        try:
            results = publish_all_meetings(connection, target, only_unpublished)
        except ValueError as exc:
            console.print(str(exc))
            raise typer.Exit(code=1) from exc

    if not results:
        console.print("No meetings to publish.")
        return
    for result in results:
        console.print(f"Published to {result.target.name}: {result.output_path}")
    console.print(f"Published {len(results)} meeting(s).")


@publish_targets_app.command("add")
def publish_targets_add(
    target_type: str,
    path: Annotated[Path, typer.Argument(file_okay=False, dir_okay=True)],
    name: Annotated[str, typer.Option("--name", "-n", help="Target name.")],
    auto_publish: Annotated[
        bool, typer.Option("--auto-publish", help="Publish processed meetings automatically.")
    ] = False,
) -> None:
    """Add an external publish target."""
    with database() as connection:
        try:
            target = add_publish_target(connection, target_type, path, name, auto_publish)
        except Exception as exc:
            console.print(str(exc))
            raise typer.Exit(code=1) from exc
    console.print(f"Added {target.target_type} publish target {target.name}")
    console.print(f"Path: {target.path}")


@publish_targets_app.command("list")
def publish_targets_list() -> None:
    """List publish targets."""
    with database() as connection:
        targets = list_publish_targets(connection)
    if not targets:
        console.print("No publish targets configured.")
        return
    table = Table(title="Publish Targets")
    table.add_column("Name")
    table.add_column("Type")
    table.add_column("Auto")
    table.add_column("Enabled")
    table.add_column("Path")
    for target in targets:
        table.add_row(
            target.name,
            target.target_type,
            "yes" if target.auto_publish else "no",
            "yes" if target.enabled else "no",
            str(target.path),
        )
    console.print(table)


@publish_targets_app.command("remove")
def publish_targets_remove(identifier: str) -> None:
    """Remove a publish target by id or name."""
    with database() as connection:
        target = remove_publish_target(connection, identifier)
    if target is None:
        console.print(f"Publish target not found: {identifier}")
        raise typer.Exit(code=1)
    console.print(f"Removed publish target {target.name}")


@publish_targets_app.command("enable")
def publish_targets_enable(identifier: str) -> None:
    """Enable a publish target by id or name."""
    _set_publish_target_enabled_command(identifier, True)


@publish_targets_app.command("disable")
def publish_targets_disable(identifier: str) -> None:
    """Disable a publish target by id or name."""
    _set_publish_target_enabled_command(identifier, False)


@meetings_app.command("list")
def meetings_list() -> None:
    """List imported meetings."""
    with database() as connection:
        meetings = list_meetings(connection)
    if not meetings:
        console.print("No meetings found. Import one with: fot import <audio>")
        return
    table = Table(title="Meetings")
    table.add_column("Slug")
    table.add_column("Title")
    table.add_column("Title Source")
    table.add_column("Language")
    for meeting in meetings:
        table.add_row(
            meeting["slug"],
            meeting["title"],
            meeting.get("title_source", "manual"),
            meeting["language"],
        )
    console.print(table)


@meetings_app.command("show")
def meetings_show(meeting: str) -> None:
    """Show one meeting."""
    with database() as connection:
        found = get_meeting(connection, meeting)
    if found is None:
        console.print(f"Meeting not found: {meeting}")
        raise typer.Exit(code=1)
    console.print(f"Title: {found['title']}")
    console.print(f"Title Source: {found.get('title_source', 'manual')}")
    if found.get("generated_title"):
        console.print(f"Generated Title: {found['generated_title']}")
    console.print(f"Slug: {found['slug']}")
    console.print(f"ID: {found['id']}")


@meetings_app.command("rename")
def meetings_rename(meeting: str, title: str) -> None:
    """Manually rename a meeting title."""
    with database() as connection:
        try:
            updated = rename_meeting(connection, meeting, title)
        except ValueError as exc:
            console.print(str(exc))
            raise typer.Exit(code=1) from exc
    console.print(f"Renamed meeting {updated['slug']}")
    console.print(f"Title: {updated['title']}")


@meetings_app.command("remove")
def meetings_remove(
    meeting: str,
    yes: Annotated[
        bool, typer.Option("--yes", "-y", help="Delete without interactive confirmation.")
    ] = False,
) -> None:
    """Completely remove a meeting and its stored files."""
    with database() as connection:
        found = get_meeting(connection, meeting)
        if found is None:
            console.print(f"Meeting not found: {meeting}")
            raise typer.Exit(code=1)

        if not yes:
            confirmed = typer.confirm(
                f"Delete meeting {found['slug']} and all stored data?", default=False
            )
            if not confirmed:
                console.print("Cancelled.")
                return

        result = delete_meeting(connection, meeting)

    console.print(f"Removed meeting {result.slug}")
    console.print(f"Removed paths: {len(result.removed_paths)}")


@app.command()
def status(meeting: str) -> None:
    """Show pipeline status for a meeting."""
    with database() as connection:
        stages = meeting_stage_status(connection, meeting)
    if not stages:
        console.print(f"No stage status found for meeting: {meeting}")
        return
    table = Table(title="Pipeline Status")
    table.add_column("Stage")
    table.add_column("Status")
    table.add_column("Error")
    for stage in stages:
        table.add_row(stage["stage_name"], stage["status"], stage["error_message"] or "")
    console.print(table)


@speakers_app.command("unknown")
def speakers_unknown(
    meeting: Annotated[
        str | None, typer.Option("--meeting", "-m", help="Meeting ID or slug.")
    ] = None,
) -> None:
    """List unknown local speakers."""
    with database() as connection:
        speakers = list_unknown_speakers(connection, meeting)
    if not speakers:
        console.print("No unknown speakers found.")
        return

    table = Table(title="Unknown Speakers")
    table.add_column("ID")
    table.add_column("Meeting")
    table.add_column("Label")
    table.add_column("Segments")
    for speaker in speakers:
        table.add_row(
            speaker["id"],
            speaker["meeting_slug"],
            speaker["label"],
            str(speaker["segment_count"]),
        )
    console.print(table)


@speakers_app.command("review")
def speakers_review(
    meeting: Annotated[
        str | None, typer.Option("--meeting", "-m", help="Meeting ID or slug.")
    ] = None,
) -> None:
    """Interactively review unknown speakers."""
    backend: EmbeddingBackend | None = None
    changed_meetings: set[str] = set()
    quit_review = False
    with database() as connection:
        speakers = list_unknown_speakers(connection, meeting)

        if not speakers:
            console.print("No unknown speakers found.")
            return

        for speaker in speakers:
            if quit_review:
                break
            console.print(f"Unknown speaker: {speaker['id']}")
            console.print(f"Meeting: {speaker['meeting_slug']}")
            console.print(f"Label: {speaker['label']}")
            examples = speaker_examples(connection, speaker["id"], limit=1)
            if examples:
                console.print(f"Example: {examples[0]['text']}")

            try:
                clip_path = prepare_speaker_review_clip(connection, speaker["id"])
            except AudioError as exc:
                clip_path = None
                console.print(f"Could not extract review clip: {exc}")

            if clip_path is not None:
                console.print(f"Clip: {clip_path}")

            while True:
                action = typer.prompt(
                    "Action [p=play, a=assign+sample, n=name only, "
                    "c=create person, u=unknown, s=skip, q=quit]",
                    default="p" if clip_path is not None else "s",
                ).strip().lower()
                if action == "p" and clip_path is not None:
                    try:
                        console.print("Playing. Press Enter to stop.")
                        play_audio(clip_path, stop_on_enter=True)
                    except AudioError as exc:
                        console.print(f"Could not play clip: {exc}")
                    continue
                if action == "a":
                    person = _select_person(connection)
                    if person is None:
                        console.print("Assignment cancelled.")
                        continue
                    backend = backend or _try_embedding_backend()
                    try:
                        result = create_voice_identity_from_speaker(
                            connection, speaker["id"], person.id, storage=None, backend=backend
                        )
                    except ValueError as exc:
                        console.print(str(exc))
                        continue
                    console.print(f"Assigned speaker to {result.person_name}")
                    console.print(f"Voice sample: {result.voice_sample.audio_path}")
                    changed_meetings.add(speaker["meeting_slug"])
                    break
                if action == "n":
                    person = _select_person(connection)
                    if person is None:
                        console.print("Assignment cancelled.")
                        continue
                    assignment = assign_speaker_to_person(connection, speaker["id"], person.id)
                    console.print(f"Assigned speaker to {assignment['name']} without voice sample.")
                    changed_meetings.add(speaker["meeting_slug"])
                    break
                if action == "c":
                    name = typer.prompt("New person name")
                    backend = backend or _try_embedding_backend()
                    try:
                        result = create_voice_identity_from_speaker(
                            connection,
                            speaker["id"],
                            name,
                            create_missing_person=True,
                            storage=None,
                            backend=backend,
                        )
                    except ValueError as exc:
                        console.print(str(exc))
                        continue
                    console.print(f"Created {result.person_name}")
                    console.print(f"Voice sample: {result.voice_sample.audio_path}")
                    changed_meetings.add(speaker["meeting_slug"])
                    break
                if action == "u":
                    mark_unknown(connection, speaker["id"])
                    console.print("Kept as unknown.")
                    changed_meetings.add(speaker["meeting_slug"])
                    break
                if action == "s":
                    console.print("Skipped.")
                    break
                if action == "q":
                    console.print("Review cancelled.")
                    quit_review = True
                    break
                console.print("Unknown action.")

        if changed_meetings and typer.confirm(
            "Refresh exports for affected meetings now?", default=True
        ):
            config = load_config()
            for meeting_slug in sorted(changed_meetings):
                result = refresh_meeting(
                    connection,
                    meeting_slug,
                    config,
                    embedding_backend=backend,
                    progress=lambda message: console.print(f"-> {message}"),
                )
                console.print(f"Refreshed {result.meeting.slug}")
                console.print(f"Transcript: {result.export.transcript_path}")
                console.print(f"Analysis: {result.export.analysis_path}")


@speakers_app.command("assign")
def speakers_assign(local_speaker_id: str, person: str) -> None:
    """Assign a local speaker to an existing person."""
    with database() as connection:
        assignment = assign_speaker_to_person(connection, local_speaker_id, person)
    console.print(f"Assigned {assignment['local_speaker_id']} to {assignment['name']}")
    console.print("Next: fot reanalyze speakers <meeting>")


@speakers_app.command("create-person")
def speakers_create_person(local_speaker_id: str, name: str) -> None:
    """Create a person from a local speaker and assign it."""
    with database() as connection:
        assignment = create_person_from_speaker(connection, local_speaker_id, name)
    console.print(f"Created and assigned {assignment['name']}")
    console.print("Next: fot reanalyze speakers <meeting>")


@reanalyze_app.command("speakers")
def reanalyze_speakers(meeting: str) -> None:
    """Rerun speaker matching and mark downstream speaker stages stale."""
    with database() as connection:
        try:
            match_count = rerun_speaker_matching(connection, meeting)
        except RuntimeError as exc:
            console.print(f"Speaker matching skipped: {exc}")
            match_count = 0
        stages = mark_speaker_reanalysis_stale(connection, meeting)
    console.print(f"Matched speakers: {match_count}")
    console.print(f"Marked stale: {', '.join(stages)}")


@reanalyze_app.command("stale")
def reanalyze_stale() -> None:
    """List stale stages that should be rerun."""
    with database() as connection:
        stale = list_stale_stages(connection)
    if not stale:
        console.print("No stale stages found.")
        return
    table = Table(title="Stale Stages")
    table.add_column("Meeting")
    table.add_column("Stage")
    for stage in stale:
        table.add_row(stage["meeting_slug"], stage["stage_name"])
    console.print(table)


@people_app.command("create")
def people_create(name: str) -> None:
    """Create a known person."""
    with database() as connection:
        person = create_person(connection, name)
    console.print(f"Created person {person.display_name}")
    console.print(f"ID: {person.id}")


@people_app.command("list")
def people_list() -> None:
    """List known people."""
    with database() as connection:
        people = list_people(connection)

    if not people:
        console.print("No people found. Create one with: fot people create \"Name\"")
        return

    table = Table(title="People")
    table.add_column("Name")
    table.add_column("User")
    table.add_column("ID")
    for person in people:
        table.add_row(person.display_name, "yes" if person.is_user else "", person.id)
    console.print(table)


@people_app.command("show")
def people_show(person: str) -> None:
    """Show one known person."""
    with database() as connection:
        found = get_person(connection, person)

    if found is None:
        console.print(f"Person not found: {person}")
        raise typer.Exit(code=1)

    console.print(f"Name: {found.display_name}")
    console.print(f"User: {'yes' if found.is_user else 'no'}")
    console.print(f"ID: {found.id}")


@people_app.command("set-user")
def people_set_user(person: str) -> None:
    """Mark one known person as the system user."""
    with database() as connection:
        try:
            updated = set_user_person(connection, person)
        except ValueError as exc:
            console.print(str(exc))
            raise typer.Exit(code=1) from exc
    console.print(f"System user: {updated.display_name}")


@people_app.command("show-user")
def people_show_user() -> None:
    """Show the person marked as the system user."""
    with database() as connection:
        person = get_user_person(connection)
    if person is None:
        console.print("No system user configured.")
        return
    console.print(f"System user: {person.display_name}")
    console.print(f"ID: {person.id}")


@people_app.command("unset-user")
def people_unset_user() -> None:
    """Clear the system user marker."""
    with database() as connection:
        person = unset_user_person(connection)
    if person is None:
        console.print("No system user configured.")
        return
    console.print(f"Cleared system user: {person.display_name}")


@people_app.command("voice-samples")
def people_voice_samples(person: str) -> None:
    """List confirmed voice samples for one person."""
    with database() as connection:
        found = get_person(connection, person)
        if found is None:
            console.print(f"Person not found: {person}")
            raise typer.Exit(code=1)
        samples = list_voice_samples(connection, found.id)

    if not samples:
        console.print("No voice samples found.")
        return

    table = Table(title=f"Voice Samples: {found.display_name}")
    table.add_column("ID")
    table.add_column("Audio")
    table.add_column("Start")
    table.add_column("End")
    for sample in samples:
        table.add_row(
            sample.id,
            str(sample.audio_path),
            "" if sample.start_time is None else f"{sample.start_time:.2f}",
            "" if sample.end_time is None else f"{sample.end_time:.2f}",
        )
    console.print(table)


def _try_embedding_backend() -> EmbeddingBackend | None:
    try:
        return PyannoteEmbeddingBackend()
    except RuntimeError as exc:
        console.print(f"Voice sample saved without embedding ({exc})")
        return None


def _scan_watch_once(config, stable_age_seconds: int) -> None:
    with database() as connection:
        result = scan_watch_folders(
            connection,
            config,
            stable_age_seconds=stable_age_seconds,
            progress=lambda message: console.print(f"-> {message}"),
        )
    console.print(
        f"Watch scan complete: {result.processed} processed, "
        f"{result.ignored} ignored, {result.skipped} skipped, "
        f"{result.failed} failed, {result.seen} seen."
    )


def _set_watch_folder_enabled_command(identifier: str, enabled: bool) -> None:
    with database() as connection:
        folder = set_watch_folder_enabled(connection, identifier, enabled)
    if folder is None:
        console.print(f"Watch folder not found: {identifier}")
        raise typer.Exit(code=1)
    state = "Enabled" if enabled else "Disabled"
    console.print(f"{state} watch folder {folder.path}")


def _set_publish_target_enabled_command(identifier: str, enabled: bool) -> None:
    with database() as connection:
        target = set_publish_target_enabled(connection, identifier, enabled)
    if target is None:
        console.print(f"Publish target not found: {identifier}")
        raise typer.Exit(code=1)
    state = "Enabled" if enabled else "Disabled"
    console.print(f"{state} publish target {target.name}")


def _select_person(connection) -> Person | None:
    people = list_people(connection)
    if not people:
        console.print("No people found. Use create person instead.")
        return None

    table = Table(title="Select Person")
    table.add_column("#")
    table.add_column("Name")
    for index, person in enumerate(people, start=1):
        table.add_row(str(index), person.display_name)
    console.print(table)

    while True:
        choice = typer.prompt("Person number [s=cancel]", default="s").strip().lower()
        if choice == "s":
            return None
        if choice.isdigit():
            index = int(choice)
            if 1 <= index <= len(people):
                return people[index - 1]
        console.print("Choose a listed number or s to cancel.")


@secrets_app.command("status")
def secrets_status() -> None:
    """Show whether API keys are available without printing values."""
    table = Table(title="Secrets")
    table.add_column("Provider")
    table.add_column("Source")
    table.add_column("Env Var")
    for provider in known_providers():
        status = get_api_key_status(provider)
        table.add_row(provider, status.source, status.env_var or "")
    console.print(table)


@secrets_app.command("set")
def secrets_set(provider: str) -> None:
    """Store an API key in the OS keyring."""
    value = typer.prompt(f"{provider} API key", hide_input=True)
    try:
        set_api_key(provider, value)
    except SecretError as exc:
        console.print(str(exc))
        raise typer.Exit(code=1) from exc
    console.print(f"Stored {provider.lower()} API key in OS keyring.")


@secrets_app.command("remove")
def secrets_remove(provider: str) -> None:
    """Remove an API key from the OS keyring."""
    try:
        remove_api_key(provider)
    except SecretError as exc:
        console.print(str(exc))
        raise typer.Exit(code=1) from exc
    console.print(f"Removed {provider.lower()} API key from OS keyring if it existed.")
