from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from fly_on_the_wall.db import database
from fly_on_the_wall.publishing import (
    add_publish_target,
    list_publish_targets,
    publish_all_meetings,
    publish_meeting,
    remove_publish_target,
    set_publish_target_enabled,
)

console = Console()
publish_app = typer.Typer(help="Publish meetings to external targets.", no_args_is_help=True)
publish_targets_app = typer.Typer(help="Manage publish targets.", no_args_is_help=True)
publish_app.add_typer(publish_targets_app, name="targets")


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


def _set_publish_target_enabled_command(identifier: str, enabled: bool) -> None:
    with database() as connection:
        target = set_publish_target_enabled(connection, identifier, enabled)
    if target is None:
        console.print(f"Publish target not found: {identifier}")
        raise typer.Exit(code=1)
    state = "Enabled" if enabled else "Disabled"
    console.print(f"{state} publish target {target.name}")
