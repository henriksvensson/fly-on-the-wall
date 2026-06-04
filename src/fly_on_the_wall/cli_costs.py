from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from fly_on_the_wall.costs import cost_summary, meeting_cost_summary
from fly_on_the_wall.db import database

console = Console()
costs_app = typer.Typer(help="Inspect external service usage and estimated costs.", no_args_is_help=True)


@costs_app.command("summary")
def costs_summary() -> None:
    """Show estimated external service costs by provider and service."""
    with database() as connection:
        rows = cost_summary(connection)
    if not rows:
        console.print("No service usage recorded yet.")
        return
    table = Table(title="Estimated Service Costs")
    table.add_column("Provider")
    table.add_column("Service")
    table.add_column("Calls", justify="right")
    table.add_column("Input", justify="right")
    table.add_column("Output", justify="right")
    table.add_column("Estimated Cost", justify="right")
    for row in rows:
        table.add_row(
            row["provider"],
            row["service"],
            str(row["calls"]),
            _format_quantity(row["input_quantity"]),
            _format_quantity(row["output_quantity"]),
            _format_usd(row["estimated_cost_usd"]),
        )
    console.print(table)


@costs_app.command("meeting")
def costs_meeting(meeting: str) -> None:
    """Show estimated external service costs for one meeting."""
    with database() as connection:
        rows = meeting_cost_summary(connection, meeting)
    if not rows:
        console.print(f"No service usage recorded for meeting: {meeting}")
        return
    table = Table(title=f"Estimated Service Costs: {meeting}")
    table.add_column("Provider")
    table.add_column("Service")
    table.add_column("Model")
    table.add_column("Calls", justify="right")
    table.add_column("Input", justify="right")
    table.add_column("Output", justify="right")
    table.add_column("Estimated Cost", justify="right")
    for row in rows:
        table.add_row(
            row["provider"],
            row["service"],
            row["model"],
            str(row["calls"]),
            _format_quantity(row["input_quantity"]),
            _format_quantity(row["output_quantity"]),
            _format_usd(row["estimated_cost_usd"]),
        )
    console.print(table)


def _format_usd(value: float | None) -> str:
    if value is None:
        return "unknown"
    return f"${value:.4f}"


def _format_quantity(value: float | None) -> str:
    if value is None:
        return "0"
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.2f}"
