from __future__ import annotations

import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from fly_on_the_wall.config import config_dir
from fly_on_the_wall.db import database
from fly_on_the_wall.watch import list_watch_folders

SERVICE_NAME = "fow-watch.service"
ENV_FILE_NAME = "service.env"
ENV_FILE_TEMPLATE = """# Optional environment variables for fow-watch.service.
# Use this if your background service cannot access API keys from the OS keyring.
# ELEVENLABS_API_KEY=
# OPENAI_API_KEY=
"""

console = Console()
service_app = typer.Typer(help="Manage the background watch service.", no_args_is_help=True)


@service_app.command("install")
def service_install(
    enable: Annotated[
        bool,
        typer.Option("--enable", help="Enable the service to start when your user session starts. Default: disabled."),
    ] = False,
    start: Annotated[
        bool,
        typer.Option("--start", help="Start the service after installing it. Default: do not start."),
    ] = False,
    force_start: Annotated[
        bool,
        typer.Option("--force-start", help="Start even when no enabled watch folders are configured."),
    ] = False,
) -> None:
    """Install the watch service for the current user."""
    _ensure_supported_platform()
    if start and not force_start:
        _ensure_enabled_watch_folders()

    unit_path = _unit_file_path()
    unit_path.parent.mkdir(parents=True, exist_ok=True)
    unit_path.write_text(render_unit(_resolve_fow_executable(), _env_file_path()), encoding="utf-8")
    console.print(f"Installed service unit: {unit_path}")
    _ensure_env_file()
    _run_or_exit(_systemctl("daemon-reload"))

    if enable:
        _run_or_exit(_systemctl("enable", SERVICE_NAME))
        console.print("Service enabled for future user sessions.")
    if start:
        _run_or_exit(_systemctl("start", SERVICE_NAME))
        console.print("Service started.")


@service_app.command("uninstall")
def service_uninstall() -> None:
    """Remove the watch service for the current user."""
    _ensure_supported_platform()
    unit_path = _unit_file_path()
    if unit_path.exists():
        _run_or_exit(_systemctl("disable", "--now", SERVICE_NAME))
        unit_path.unlink()
        console.print(f"Removed service unit: {unit_path}")
    else:
        console.print(f"Service unit was not installed: {unit_path}")
    _run_or_exit(_systemctl("daemon-reload"))


@service_app.command("start")
def service_start(
    force: Annotated[
        bool,
        typer.Option("--force", help="Start even when no enabled watch folders are configured."),
    ] = False,
) -> None:
    """Start the watch service."""
    _run_watch_service_action("start", force)


@service_app.command("stop")
def service_stop() -> None:
    """Stop the watch service."""
    _ensure_supported_platform()
    _run_or_exit(_systemctl("stop", SERVICE_NAME))


@service_app.command("restart")
def service_restart(
    force: Annotated[
        bool,
        typer.Option("--force", help="Restart even when no enabled watch folders are configured."),
    ] = False,
) -> None:
    """Restart the watch service."""
    _run_watch_service_action("restart", force)


def _run_watch_service_action(action: str, force: bool) -> None:
    _ensure_supported_platform()
    if not force:
        _ensure_enabled_watch_folders()
    _run_or_exit(_systemctl(action, SERVICE_NAME))


@service_app.command("status")
def service_status() -> None:
    """Show watch service status."""
    _ensure_supported_platform()
    _run_or_exit(["systemctl", "--user", "--no-pager", "status", SERVICE_NAME])


@service_app.command("logs")
def service_logs(
    lines: Annotated[int, typer.Option("--lines", "-n", min=1, help="Number of recent log lines to show.")] = 100,
    follow: Annotated[bool, typer.Option("--follow", "-f", help="Follow logs until interrupted.")] = False,
) -> None:
    """Show watch service logs."""
    _ensure_supported_platform()
    command = ["journalctl", "--user", "-u", SERVICE_NAME, "-n", str(lines)]
    if follow:
        command.append("--follow")
    else:
        command.append("--no-pager")
    _run_or_exit(command)


@service_app.command("print-unit")
def service_print_unit() -> None:
    """Print the generated service unit without installing it."""
    _ensure_supported_platform()
    console.print(render_unit(_resolve_fow_executable(), _env_file_path()), end="", markup=False)


def render_unit(fow_executable: Path, env_file_path: Path) -> str:
    if not fow_executable.is_absolute():
        raise ValueError("fow executable path must be absolute")
    if not env_file_path.is_absolute():
        raise ValueError("service environment file path must be absolute")
    return f"""[Unit]
Description=Fly on the Wall watch service
After=default.target

[Service]
Type=simple
Environment=PYTHONUNBUFFERED=1
EnvironmentFile=-{_systemd_quote(env_file_path)}
ExecStart={_systemd_quote(fow_executable)} watch run
Restart=on-failure
RestartSec=10

[Install]
WantedBy=default.target
"""


def _ensure_supported_platform() -> None:
    if sys.platform != "linux":
        console.print("Unsupported platform: fow service currently supports Linux systemd user services only.")
        raise typer.Exit(code=1)


def _ensure_enabled_watch_folders() -> None:
    if _has_enabled_watch_folder():
        return
    console.print("No enabled watch folders configured; the watch service would exit immediately.")
    console.print("Add one with: fow watch folders add <path>")
    console.print("To start anyway, pass --force or --force-start.")
    raise typer.Exit(code=1)


def _has_enabled_watch_folder() -> bool:
    with database() as connection:
        return any(folder.enabled for folder in list_watch_folders(connection))


def _resolve_fow_executable() -> Path:
    executable = shutil.which("fow")
    if executable is None:
        console.print("Could not find the fow executable on PATH.")
        raise typer.Exit(code=1)
    return Path(executable).resolve()


def _unit_file_path() -> Path:
    return config_dir().parent / "systemd" / "user" / SERVICE_NAME


def _env_file_path() -> Path:
    return config_dir() / ENV_FILE_NAME


def _ensure_env_file() -> None:
    env_path = _env_file_path()
    if env_path.exists():
        console.print(f"Service environment file already exists: {env_path}")
        return
    env_path.parent.mkdir(parents=True, exist_ok=True)
    env_path.write_text(ENV_FILE_TEMPLATE, encoding="utf-8")
    env_path.chmod(0o600)
    console.print(f"Created service environment placeholder: {env_path}")


def _systemctl(*arguments: str) -> list[str]:
    return ["systemctl", "--user", *arguments]


def _run_or_exit(command: Sequence[str]) -> None:
    try:
        _run_command(command)
    except FileNotFoundError as exc:
        console.print(f"Required command not found: {command[0]}")
        raise typer.Exit(code=1) from exc
    except subprocess.CalledProcessError as exc:
        console.print(f"Command failed with exit code {exc.returncode}: {' '.join(command)}")
        raise typer.Exit(code=exc.returncode) from exc


def _run_command(command: Sequence[str]) -> None:
    subprocess.run(command, check=True)


def _systemd_quote(path: Path) -> str:
    text = str(path)
    if not any(character.isspace() for character in text) and '"' not in text:
        return text
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'
