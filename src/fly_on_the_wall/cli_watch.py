from __future__ import annotations

from pathlib import Path
from time import sleep
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table
from watchfiles import watch

from fly_on_the_wall.config import load_config
from fly_on_the_wall.db import database
from fly_on_the_wall.watch import (
    DEFAULT_STABLE_AGE_SECONDS,
    add_watch_folder,
    list_watch_folders,
    remove_watch_folder,
    scan_watch_folders,
    set_watch_folder_enabled,
)

console = Console()
watch_app = typer.Typer(help="Process audio from watched folders.", no_args_is_help=True)
watch_folders_app = typer.Typer(help="Manage watched folders.", no_args_is_help=True)
watch_app.add_typer(watch_folders_app, name="folders")


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
    _scan_watch_once(load_config(), stable_age_seconds)


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
    folders = _enabled_watch_folders()
    if not folders:
        console.print("No enabled watch folders configured.")
        console.print("Add one with: fow watch folders add <path>")
        raise typer.Exit(code=1)

    console.print("Watching folders for audio changes. Press Ctrl+C to stop.")
    for path in [folder.path for folder in folders]:
        console.print(f"- {path}")

    _scan_watch_once(config, stable_age_seconds)
    while True:
        _watch_run_once(config, stable_age_seconds, interval_seconds)


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


def _watch_run_once(config, stable_age_seconds: int, interval_seconds: int) -> None:
    existing_paths = _existing_watch_paths()
    if not existing_paths:
        console.print("No watched folders are currently mounted. Running safety scan.")
        _scan_watch_once(config, stable_age_seconds)
        sleep(interval_seconds)
        return

    changes = _watch_for_changes(existing_paths, interval_seconds)
    if changes is None:
        _scan_watch_once(config, stable_age_seconds)
        return

    _print_watch_changes(changes)
    _scan_watch_once(config, stable_age_seconds)


def _enabled_watch_folders():
    with database() as connection:
        return [folder for folder in list_watch_folders(connection) if folder.enabled]


def _existing_watch_paths() -> list[Path]:
    return [folder.path for folder in _enabled_watch_folders() if folder.path.is_dir()]


def _watch_for_changes(paths: list[Path], interval_seconds: int):
    try:
        return next(
            watch(
                *paths,
                recursive=True,
                yield_on_timeout=True,
                rust_timeout=interval_seconds * 1000,
            )
        )
    except (OSError, RuntimeError) as exc:
        console.print(f"Watch backend restarted after folder change: {exc}")
        return None


def _print_watch_changes(changes) -> None:
    if changes:
        console.print(f"Detected {len(changes)} file change(s).")
        return
    console.print("Running periodic safety scan.")


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
