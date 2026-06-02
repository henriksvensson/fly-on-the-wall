from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from fly_on_the_wall import __version__
from fly_on_the_wall.config import load_config
from fly_on_the_wall.db import database
from fly_on_the_wall.doctor import has_failures, run_checks
from fly_on_the_wall.meetings import (
    get_meeting,
    import_meeting,
    list_meetings,
    meeting_stage_status,
)
from fly_on_the_wall.people import create_person, get_person, list_people
from fly_on_the_wall.processing import process_audio
from fly_on_the_wall.speakers import list_unknown_speakers

app = typer.Typer(
    name="fot",
    help="Personal CLI note-taker for meeting audio.",
    no_args_is_help=True,
)
people_app = typer.Typer(help="Manage known people.", no_args_is_help=True)
meetings_app = typer.Typer(help="Inspect meetings.", no_args_is_help=True)
speakers_app = typer.Typer(help="Review and assign speakers.", no_args_is_help=True)
app.add_typer(people_app, name="people")
app.add_typer(meetings_app, name="meetings")
app.add_typer(speakers_app, name="speakers")
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
    title: Annotated[str, typer.Option("--title", "-t", help="Meeting title.")],
    description: Annotated[
        str | None, typer.Option("--description", "-d", help="Meeting context.")
    ] = None,
) -> None:
    """Import an audio file into application storage."""
    config = load_config()
    with database() as connection:
        meeting = import_meeting(connection, audio_path, title, config, description=description)

    console.print(f"Imported meeting {meeting.slug}")
    console.print(f"ID: {meeting.id}")
    console.print(f"Audio: {meeting.imported_audio_path}")


@app.command()
def process(
    audio_path: Annotated[Path, typer.Argument(exists=True, file_okay=True, dir_okay=False)],
    title: Annotated[str, typer.Option("--title", "-t", help="Meeting title.")],
    description: Annotated[
        str | None, typer.Option("--description", "-d", help="Meeting context.")
    ] = None,
) -> None:
    """Process audio from import through markdown export."""
    config = load_config()
    with database() as connection:
        result = process_audio(connection, audio_path, title, config, description=description)

    console.print(f"Processed meeting {result.meeting.slug}")
    console.print(f"Export: {result.export.transcript_path}")


@meetings_app.command("list")
def meetings_list() -> None:
    """List imported meetings."""
    with database() as connection:
        meetings = list_meetings(connection)
    if not meetings:
        console.print("No meetings found.")
        return
    table = Table(title="Meetings")
    table.add_column("Slug")
    table.add_column("Title")
    table.add_column("Language")
    for meeting in meetings:
        table.add_row(meeting["slug"], meeting["title"], meeting["language"])
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
    console.print(f"Slug: {found['slug']}")
    console.print(f"ID: {found['id']}")


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
        console.print("No people found.")
        return

    table = Table(title="People")
    table.add_column("Name")
    table.add_column("ID")
    for person in people:
        table.add_row(person.display_name, person.id)
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
    console.print(f"ID: {found.id}")
