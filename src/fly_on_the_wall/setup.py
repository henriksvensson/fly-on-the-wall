from __future__ import annotations

import importlib.util
from pathlib import Path
from shutil import which

import typer
from rich.console import Console
from rich.table import Table

from fly_on_the_wall.db import database
from fly_on_the_wall.doctor import run_checks
from fly_on_the_wall.people import create_person, get_person, get_user_person, set_user_person
from fly_on_the_wall.people_embeddings import people_embedding_status
from fly_on_the_wall.publishing import add_publish_target, list_publish_targets
from fly_on_the_wall.secrets import SecretError, get_api_key_status, known_providers, set_api_key
from fly_on_the_wall.storage import storage_paths
from fly_on_the_wall.watch import add_watch_folder, list_watch_folders


def run_setup(console: Console) -> None:
    """Run the interactive first-run setup wizard."""
    console.print("Fly on the Wall setup")
    console.print("This command checks required setup and can configure optional features.")
    console.print("")

    _show_runtime_summary(console)
    _setup_secrets(console)
    _setup_user_identity(console)
    _setup_speaker_identity(console)
    _setup_publishing(console)
    _setup_watch_folders(console)
    _show_final_summary(console)


def _show_runtime_summary(console: Console) -> None:
    checks = run_checks()
    table = Table(title="Setup Checks")
    table.add_column("Check")
    table.add_column("Status")
    table.add_column("Detail")
    for check in checks:
        table.add_row(check.name, "ok" if check.ok else "missing", check.detail)
    console.print(table)

    if which("ffmpeg") is None:
        console.print("FFmpeg is required for audio processing.")
        console.print("Install it with your OS package manager, then run `fot doctor`.")
    console.print("")


def _setup_secrets(console: Console) -> None:
    console.print("Secrets")
    for provider in ["elevenlabs", "openai"]:
        _setup_secret(console, provider)

    other_providers = [provider for provider in known_providers() if provider not in {"elevenlabs", "openai"}]
    if other_providers:
        console.print("Other provider keys can be configured later with `fot secrets set <provider>`.")
    console.print("")


def _setup_secret(console: Console, provider: str) -> None:
    status = get_api_key_status(provider)
    if status.available:
        console.print(f"- {provider}: configured via {status.source}")
        return
    if not typer.confirm(f"Store a {provider} API key in the OS keyring?", default=False):
        console.print(f"- {provider}: skipped")
        return
    value = typer.prompt(f"{provider} API key", hide_input=True).strip()
    if not value:
        console.print(f"- {provider}: skipped empty value")
        return
    try:
        set_api_key(provider, value)
    except SecretError as exc:
        console.print(str(exc))
        return
    console.print(f"- {provider}: stored in OS keyring")


def _setup_user_identity(console: Console) -> None:
    with database() as connection:
        user = get_user_person(connection)
        if user is not None:
            console.print(f"User identity: {user.display_name}")
            console.print("")
            return

        if not typer.confirm("Set your own person identity for speaker matching?", default=True):
            console.print("User identity: skipped")
            console.print("")
            return

        display_name = typer.prompt("Your display name").strip()
        if not display_name:
            console.print("User identity: skipped empty name")
            console.print("")
            return
        person = get_person(connection, display_name) or create_person(connection, display_name)
        set_user_person(connection, person.id)
    console.print(f"User identity: {display_name}")
    console.print("")


def _setup_speaker_identity(console: Console) -> None:
    console.print("Speaker identity")
    if _identity_dependencies_available():
        with database() as connection:
            status = people_embedding_status(connection)
        console.print("- local speaker identity dependencies: available")
        console.print("- voice sample embeddings: " f"{status.embedded_voice_samples}/{status.voice_samples} embedded")
        if status.missing_voice_sample_embeddings:
            console.print("Run `fot people embeddings backfill` to embed missing voice samples.")
        console.print("")
        return

    console.print("- local speaker identity dependencies: missing")
    if typer.confirm("Do you want guidance for enabling recurring speaker identity?", default=True):
        console.print("Install or upgrade the package with the identity extra, then rerun setup:")
        console.print('  uv tool install "fly-on-the-wall[identity]"')
        console.print('  uv tool upgrade --reinstall "fly-on-the-wall[identity]"')
        console.print('  pipx install "fly-on-the-wall[identity]"')
        console.print('  pipx inject fly-on-the-wall "fly-on-the-wall[identity]"')
        console.print("If you installed from source, run `uv sync --extra identity`.")
    console.print("")


def _identity_dependencies_available() -> bool:
    return all(_module_available(module) for module in ["pyannote.audio", "torch", "torchaudio"])


def _setup_publishing(console: Console) -> None:
    with database() as connection:
        targets = list_publish_targets(connection)
        if targets:
            console.print("Publishing")
            for target in targets:
                console.print(f"- {target.name}: {target.path}")
            console.print("")
            return

        if not typer.confirm("Publish notes to an Obsidian folder?", default=False):
            console.print("Publishing: skipped")
            console.print("")
            return

        path = Path(typer.prompt("Obsidian folder path")).expanduser()
        name = typer.prompt("Target name", default="obsidian").strip() or "obsidian"
        auto_publish = typer.confirm("Auto-publish processed/refreshed meetings?", default=True)
        path.mkdir(parents=True, exist_ok=True)
        target = add_publish_target(connection, "obsidian", path, name, auto_publish=auto_publish)
    console.print(f"Publishing: added {target.name} -> {target.path}")
    console.print("")


def _setup_watch_folders(console: Console) -> None:
    with database() as connection:
        folders = list_watch_folders(connection)
        if folders:
            _print_watch_folders(console, folders)
            console.print("")
            return

        if not typer.confirm("Watch folders for new recordings?", default=False):
            console.print("Watched folders: skipped")
            console.print("")
            return

        while True:
            _prompt_watch_folder(console, connection)
            if not typer.confirm("Add another watched folder?", default=False):
                break
    console.print("")


def _print_watch_folders(console: Console, folders: list) -> None:
    console.print("Watched folders")
    for folder in folders:
        state = "enabled" if folder.enabled else "disabled"
        console.print(f"- {folder.path} ({state})")


def _prompt_watch_folder(console: Console, connection) -> None:
    path_text = typer.prompt("Folder path to watch").strip()
    if not path_text:
        return
    name = typer.prompt("Folder name", default="").strip() or None
    folder = add_watch_folder(connection, Path(path_text), name)
    console.print(f"Added watch folder: {folder.path}")


def _show_final_summary(console: Console) -> None:
    paths = storage_paths()
    checks = run_checks()
    required_failures = [
        check for check in checks if check.name in {"python", "ffmpeg", "elevenlabs api key"} and not check.ok
    ]

    console.print("Setup summary")
    console.print(f"- App data: {paths.root}")
    console.print(f"- Required setup: {'ready' if not required_failures else 'incomplete'}")
    if required_failures:
        for check in required_failures:
            console.print(f"  missing: {check.name} ({check.detail})")
        console.print("Run `fot doctor` after fixing missing items.")
    else:
        console.print("Fly on the Wall is ready.")
        console.print("Next: `fot process path/to/meeting.m4a`")


def _module_available(module_name: str) -> bool:
    try:
        return importlib.util.find_spec(module_name) is not None
    except ModuleNotFoundError:
        return False
