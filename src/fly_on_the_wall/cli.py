from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from fly_on_the_wall import __version__
from fly_on_the_wall.doctor import has_failures, run_checks

app = typer.Typer(
    name="fot",
    help="Personal CLI note-taker for meeting audio.",
    no_args_is_help=True,
)
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
