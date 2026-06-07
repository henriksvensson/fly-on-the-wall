from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from fly_on_the_wall import __version__
from fly_on_the_wall.cli_costs import costs_app
from fly_on_the_wall.cli_publish import publish_app
from fly_on_the_wall.cli_speaker_review import speakers_review
from fly_on_the_wall.cli_watch import watch_app
from fly_on_the_wall.config import load_config
from fly_on_the_wall.db import database
from fly_on_the_wall.doctor import has_failures, run_checks
from fly_on_the_wall.meetings import (
    delete_meeting,
    get_meeting,
    list_meetings,
    meeting_stage_status,
    rename_meeting,
)
from fly_on_the_wall.people import (
    create_person,
    get_person,
    get_user_person,
    list_people,
    set_user_person,
    unset_user_person,
)
from fly_on_the_wall.people_embeddings import (
    backfill_people_embeddings,
    people_embedding_status,
)
from fly_on_the_wall.processing import process_audio, refresh_meeting
from fly_on_the_wall.reanalysis import (
    list_stale_meetings,
    list_stale_stages,
    mark_speaker_reanalysis_stale,
    rerun_speaker_matching,
    rerun_speaker_matching_for_meetings,
)
from fly_on_the_wall.recording_quality import RecordingIgnoredError
from fly_on_the_wall.secrets import (
    SecretError,
    get_api_key_status,
    known_providers,
    remove_api_key,
    set_api_key,
)
from fly_on_the_wall.setup import run_setup
from fly_on_the_wall.speakers import (
    assign_speaker_to_person,
    list_unknown_speakers,
    mark_speaker_ignored,
)
from fly_on_the_wall.voice_samples import list_voice_samples

app = typer.Typer(
    name="fow",
    help="Personal CLI note-taker for meeting audio.",
    no_args_is_help=True,
)
people_app = typer.Typer(help="Manage known people.", no_args_is_help=True)
people_embeddings_app = typer.Typer(help="Manage known people's voice embeddings.", no_args_is_help=True)
meetings_app = typer.Typer(help="Inspect meetings.", no_args_is_help=True)
meeting_speakers_app = typer.Typer(
    help="Review meeting-local speakers and assign them to people.",
    no_args_is_help=True,
)
refresh_app = typer.Typer(help="Refresh derived meeting outputs.", no_args_is_help=True)
secrets_app = typer.Typer(help="Manage API keys in the OS keyring.", no_args_is_help=True)
app.add_typer(people_app, name="people")
people_app.add_typer(people_embeddings_app, name="embeddings")
app.add_typer(meetings_app, name="meetings")
meetings_app.add_typer(meeting_speakers_app, name="speakers")
app.add_typer(refresh_app, name="refresh")
app.add_typer(secrets_app, name="secrets")
app.add_typer(watch_app, name="watch")
app.add_typer(publish_app, name="publish")
app.add_typer(costs_app, name="costs")
console = Console()
meeting_speakers_app.command("review")(speakers_review)


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
def setup() -> None:
    """Interactively configure first-run setup."""
    run_setup(console)


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


@app.command()
def process(
    audio_path: Annotated[Path, typer.Argument(exists=True, file_okay=True, dir_okay=False)],
    title: Annotated[str | None, typer.Option("--title", "-t", help="Manual meeting title override.")] = None,
    description: Annotated[str | None, typer.Option("--description", "-d", help="Meeting context.")] = None,
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
    console.print(f"Review unknown speakers: fow meetings speakers unknown --meeting {result.meeting.slug}")


@meetings_app.command("list")
def meetings_list() -> None:
    """List imported meetings."""
    with database() as connection:
        meetings = list_meetings(connection)
    if not meetings:
        console.print("No meetings found. Process one with: fow process <audio>")
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
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Delete without interactive confirmation.")] = False,
    delete_published: Annotated[
        bool,
        typer.Option("--delete-published", help="Also delete externally published notes for this meeting."),
    ] = False,
) -> None:
    """Completely remove a meeting and its stored files."""
    with database() as connection:
        found = get_meeting(connection, meeting)
        if found is None:
            console.print(f"Meeting not found: {meeting}")
            raise typer.Exit(code=1)

        if not yes:
            message = f"Delete meeting {found['slug']} and all stored data?"
            if delete_published:
                message += " This will also delete externally published notes."
            confirmed = typer.confirm(message, default=False)
            if not confirmed:
                console.print("Cancelled.")
                return
            if not delete_published and _meeting_has_published_items(connection, found["id"]):
                delete_published = typer.confirm(
                    "Delete externally published notes for this meeting too?",
                    default=False,
                )

        result = delete_meeting(connection, meeting, delete_published=delete_published)

    console.print(f"Removed meeting {result.slug}")


def _meeting_has_published_items(connection, meeting_id: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM published_items WHERE meeting_id = ? LIMIT 1",
        (meeting_id,),
    ).fetchone()
    return row is not None


@meetings_app.command("status")
def meetings_status(meeting: str) -> None:
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


@meeting_speakers_app.command("unknown")
def speakers_unknown(
    meeting: Annotated[str | None, typer.Option("--meeting", "-m", help="Meeting ID or slug.")] = None,
) -> None:
    """List meeting-local speakers that are not assigned to people."""
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


@meeting_speakers_app.command("assign")
def speakers_assign(local_speaker_id: str, person: str) -> None:
    """Assign a meeting-local speaker to a person, creating that person if needed."""
    with database() as connection:
        assignment = assign_speaker_to_person(connection, local_speaker_id, person)
    if assignment["created_person"]:
        console.print(f"Created person {assignment['name']}")
    console.print(f"Assigned {assignment['local_speaker_id']} to {assignment['name']}")
    console.print("Next: fow refresh speakers <meeting>")


@meeting_speakers_app.command("ignore")
def speakers_ignore(local_speaker_id: str) -> None:
    """Ignore a meeting-local speaker so it is not shown during review."""
    with database() as connection:
        try:
            mark_speaker_ignored(connection, local_speaker_id)
        except ValueError as exc:
            console.print(str(exc))
            raise typer.Exit(code=1) from exc
    console.print(f"Ignored meeting speaker {local_speaker_id}")


@refresh_app.command("speakers")
def refresh_speakers(
    meeting: Annotated[str | None, typer.Argument(help="Optional meeting ID or slug.")] = None,
    include_known_speakers: Annotated[
        bool,
        typer.Option(
            "--include-known-speakers",
            help="Also refresh speaker matching for meetings where all speakers are already known.",
        ),
    ] = False,
) -> None:
    """Refresh speaker matching and mark downstream outputs stale."""
    with database() as connection:
        if meeting is None:
            _refresh_speakers_for_all_meetings(connection, include_known_speakers)
            return

        match_count = _refresh_speakers_for_one_meeting(connection, meeting)
        stages = mark_speaker_reanalysis_stale(connection, meeting) if match_count else []
    console.print(f"New speaker matches: {match_count}")
    if stages:
        console.print(f"Marked stale: {', '.join(stages)}")
    else:
        console.print("No speaker assignment changes; downstream stages left untouched.")


def _refresh_speakers_for_all_meetings(connection, include_known_speakers: bool) -> None:
    results = rerun_speaker_matching_for_meetings(
        connection,
        include_known_speakers,
        progress=lambda message: console.print(f"-> {message}"),
    )
    if not results:
        console.print("No meetings found for speaker refresh.")
        return
    _print_speaker_refresh_results(results)


def _print_speaker_refresh_results(results) -> None:
    table = Table(title="Speaker Refresh")
    table.add_column("Meeting")
    table.add_column("New Speaker Matches")
    for result in results:
        table.add_row(result["meeting_slug"], str(result["match_count"]))
    console.print(table)
    console.print(f"Speaker matching refreshed for meetings: {len(results)}")
    _print_speaker_refresh_next_step(results)


def _print_speaker_refresh_next_step(results) -> None:
    if any(result["match_count"] for result in results):
        console.print("Next: fow refresh stale-meetings")
        return
    console.print("No speaker assignment changes; downstream stages left untouched.")


def _refresh_speakers_for_one_meeting(connection, meeting: str) -> int:
    try:
        return rerun_speaker_matching(
            connection,
            meeting,
            progress=lambda message: console.print(f"-> {message}"),
        )
    except RuntimeError as exc:
        console.print(f"Speaker matching skipped: {exc}")
        return 0


@refresh_app.command("stale-meetings")
def refresh_stale_meetings(
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="List stale meetings without refreshing them."),
    ] = False,
) -> None:
    """Refresh all meetings with stale derived outputs."""
    with database() as connection:
        stale_meetings = list_stale_meetings(connection)
        if not stale_meetings:
            console.print("No stale meetings found.")
            return
        if dry_run:
            _print_stale_stages(connection)
            return

        config = load_config()
        results: list[tuple[str, str, str]] = []
        for stale_meeting in stale_meetings:
            meeting_slug = stale_meeting["meeting_slug"]
            try:
                result = refresh_meeting(
                    connection,
                    meeting_slug,
                    config,
                    progress=lambda message: console.print(f"-> {message}"),
                )
            except (RecordingIgnoredError, ValueError) as exc:
                console.print(f"Refresh failed for {meeting_slug}: {exc}")
                results.append((meeting_slug, "failed", ""))
                continue
            results.append((result.meeting.slug, "refreshed", str(result.export.transcript_path)))

    table = Table(title="Refresh Stale Meetings")
    table.add_column("Meeting")
    table.add_column("Status")
    table.add_column("Transcript")
    for meeting_slug, status, transcript_path in results:
        table.add_row(meeting_slug, status, transcript_path)
    console.print(table)


@refresh_app.command("meeting")
def refresh_meeting_command(meeting: str) -> None:
    """Refresh derived outputs for one meeting."""
    config = load_config()
    with database() as connection:
        try:
            result = refresh_meeting(
                connection,
                meeting,
                config,
                progress=lambda message: console.print(f"-> {message}"),
            )
        except (RecordingIgnoredError, ValueError) as exc:
            console.print(str(exc))
            raise typer.Exit(code=1) from exc
    console.print(f"Refreshed {result.meeting.slug}")
    console.print(f"Transcript: {result.export.transcript_path}")
    console.print(f"Analysis: {result.export.analysis_path}")


def _print_stale_stages(connection) -> None:
    stale = list_stale_stages(connection)
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
        console.print('No people found. Create one with: fow people create "Name"')
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


@people_embeddings_app.command("status")
def people_embeddings_status() -> None:
    """Show voice embedding coverage for known people."""
    with database() as connection:
        status = people_embedding_status(connection)

    table = Table(title="People Voice Embeddings")
    table.add_column("Metric")
    table.add_column("Value")
    table.add_row("People", str(status.people))
    table.add_row("Voice samples", str(status.voice_samples))
    table.add_row("Embedded voice samples", str(status.embedded_voice_samples))
    table.add_row(
        "Missing voice sample embeddings",
        str(status.missing_voice_sample_embeddings),
    )
    console.print(table)


@people_embeddings_app.command("backfill")
def people_embeddings_backfill() -> None:
    """Create missing voice embeddings for known people."""
    try:
        with database() as connection:
            result = backfill_people_embeddings(connection)
    except RuntimeError as exc:
        console.print(str(exc))
        raise typer.Exit(code=1) from exc

    console.print(f"People voice embedding backfill complete: {result.embedded} embedded, {result.failed} failed.")
    if result.embedded:
        console.print("Next: fow refresh speakers")


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
        _print_secret_env_fallback(provider)
        raise typer.Exit(code=1) from exc
    console.print(f"Stored {provider.lower()} API key in OS keyring.")


def _print_secret_env_fallback(provider: str) -> None:
    status = get_api_key_status(provider)
    if status.env_var:
        console.print(f"Alternative: set {status.env_var} in your shell environment.")


@secrets_app.command("remove")
def secrets_remove(provider: str) -> None:
    """Remove an API key from the OS keyring."""
    try:
        remove_api_key(provider)
    except SecretError as exc:
        console.print(str(exc))
        raise typer.Exit(code=1) from exc
    console.print(f"Removed {provider.lower()} API key from OS keyring if it existed.")
