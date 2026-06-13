from __future__ import annotations

from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from fly_on_the_wall.db import database
from fly_on_the_wall.glossary import (
    create_glossary_term,
    get_glossary_term,
    list_glossary_terms,
    remove_glossary_term,
    update_glossary_term,
)

glossary_app = typer.Typer(help="Manage transcription and cleanup glossary terms.", no_args_is_help=True)
console = Console()


@glossary_app.command("add")
def glossary_add(
    term: str,
    description: Annotated[str | None, typer.Option("--description", "-d", help="Optional context.")] = None,
) -> None:
    """Add a word or phrase to the glossary."""
    with database() as connection:
        try:
            created = create_glossary_term(connection, term, description)
        except ValueError as exc:
            console.print(str(exc))
            raise typer.Exit(code=1) from exc
    console.print(f"Added glossary term: {created.term}")


@glossary_app.command("list")
def glossary_list(
    all_terms: Annotated[bool, typer.Option("--all", help="Include disabled terms.")] = False,
) -> None:
    """List glossary terms."""
    with database() as connection:
        terms = list_glossary_terms(connection, include_disabled=all_terms)
    if not terms:
        console.print("No glossary terms found.")
        return

    table = Table(title="Glossary")
    table.add_column("Term")
    table.add_column("Description")
    table.add_column("Enabled")
    for term in terms:
        table.add_row(term.term, term.description or "", "yes" if term.enabled else "no")
    console.print(table)


@glossary_app.command("show")
def glossary_show(term: str) -> None:
    """Show one glossary term."""
    with database() as connection:
        found = get_glossary_term(connection, term)
    if found is None:
        console.print(f"Glossary term not found: {term}")
        raise typer.Exit(code=1)
    console.print(f"Term: {found.term}")
    console.print(f"Description: {found.description or ''}")
    console.print(f"Enabled: {'yes' if found.enabled else 'no'}")
    console.print(f"ID: {found.id}")


@glossary_app.command("update")
def glossary_update(
    term: str,
    new_term: Annotated[str | None, typer.Option("--term", help="Replace the glossary term text.")] = None,
    description: Annotated[str | None, typer.Option("--description", "-d", help="Replace the description.")] = None,
) -> None:
    """Update a glossary term or description."""
    with database() as connection:
        try:
            updated = update_glossary_term(connection, term, term=new_term, description=description)
        except ValueError as exc:
            console.print(str(exc))
            raise typer.Exit(code=1) from exc
    console.print(f"Updated glossary term: {updated.term}")


@glossary_app.command("enable")
def glossary_enable(term: str) -> None:
    """Enable a glossary term."""
    _set_enabled(term, True)


@glossary_app.command("disable")
def glossary_disable(term: str) -> None:
    """Disable a glossary term without deleting it."""
    _set_enabled(term, False)


@glossary_app.command("remove")
def glossary_remove(
    term: str,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Remove without confirmation.")] = False,
) -> None:
    """Remove a glossary term."""
    if not yes and not typer.confirm(f"Remove glossary term '{term}'?", default=False):
        console.print("Cancelled.")
        return
    with database() as connection:
        removed = remove_glossary_term(connection, term)
    if not removed:
        console.print(f"Glossary term not found: {term}")
        raise typer.Exit(code=1)
    console.print(f"Removed glossary term: {term}")


def _set_enabled(term: str, enabled: bool) -> None:
    with database() as connection:
        try:
            updated = update_glossary_term(connection, term, enabled=enabled)
        except ValueError as exc:
            console.print(str(exc))
            raise typer.Exit(code=1) from exc
    state = "Enabled" if enabled else "Disabled"
    console.print(f"{state} glossary term: {updated.term}")
