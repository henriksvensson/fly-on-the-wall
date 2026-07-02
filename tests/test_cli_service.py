from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

import pytest
from typer.testing import CliRunner

import fly_on_the_wall.cli_service as cli_service
from fly_on_the_wall.cli import app

runner = CliRunner()


def patch_no_enabled_watch_folders(monkeypatch) -> None:
    @contextmanager
    def fake_database():
        yield object()

    monkeypatch.setattr(cli_service.sys, "platform", "linux")
    monkeypatch.setattr(cli_service, "database", fake_database)
    monkeypatch.setattr(cli_service, "list_watch_folders", lambda connection: [])


def test_service_group_exists() -> None:
    result = runner.invoke(app, ["service", "--help"])

    assert result.exit_code == 0
    assert "Manage the background watch service" in result.stdout


def test_render_unit_uses_absolute_fow_path() -> None:
    unit = cli_service.render_unit(Path("/usr/local/bin/fow"), Path("/home/user/.config/fly-on-the-wall/service.env"))

    assert "Environment=PYTHONUNBUFFERED=1" in unit
    assert "EnvironmentFile=-/home/user/.config/fly-on-the-wall/service.env" in unit
    assert "ExecStart=/usr/local/bin/fow watch run" in unit
    assert "Restart=on-failure" in unit


def test_render_unit_requires_absolute_fow_path() -> None:
    with pytest.raises(ValueError, match="absolute"):
        cli_service.render_unit(Path("fow"), Path("/home/user/.config/fly-on-the-wall/service.env"))


def test_render_unit_requires_absolute_env_file_path() -> None:
    with pytest.raises(ValueError, match="environment file"):
        cli_service.render_unit(Path("/usr/local/bin/fow"), Path("service.env"))


def test_install_writes_unit_and_runs_requested_actions(monkeypatch, tmp_path) -> None:
    calls = []

    @contextmanager
    def fake_database():
        yield object()

    folder = type("Folder", (), {"enabled": True})()

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setattr(cli_service.sys, "platform", "linux")
    monkeypatch.setattr(cli_service.shutil, "which", lambda command: "/usr/local/bin/fow")
    monkeypatch.setattr(cli_service, "database", fake_database)
    monkeypatch.setattr(cli_service, "list_watch_folders", lambda connection: [folder])
    monkeypatch.setattr(cli_service, "_run_command", lambda command: calls.append(list(command)))

    result = runner.invoke(app, ["service", "install", "--enable", "--start"])

    unit_path = tmp_path / ".config" / "systemd" / "user" / "fow-watch.service"
    env_path = tmp_path / ".config" / "fly-on-the-wall" / "service.env"
    assert result.exit_code == 0
    assert unit_path.read_text(encoding="utf-8") == cli_service.render_unit(Path("/usr/local/bin/fow"), env_path)
    assert env_path.read_text(encoding="utf-8") == cli_service.ENV_FILE_TEMPLATE
    assert calls == [
        ["systemctl", "--user", "daemon-reload"],
        ["systemctl", "--user", "enable", "fow-watch.service"],
        ["systemctl", "--user", "start", "fow-watch.service"],
    ]


def test_install_refuses_to_start_without_enabled_watch_folders(monkeypatch, tmp_path) -> None:
    calls = []

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    patch_no_enabled_watch_folders(monkeypatch)
    monkeypatch.setattr(cli_service, "_run_command", lambda command: calls.append(list(command)))

    result = runner.invoke(app, ["service", "install", "--start"])

    assert result.exit_code == 1
    assert "No enabled watch folders configured" in result.stdout
    assert calls == []
    assert not (tmp_path / ".config" / "systemd" / "user" / "fow-watch.service").exists()


def test_install_force_start_skips_watch_folder_check(monkeypatch, tmp_path) -> None:
    calls = []

    def fail_if_called():
        raise AssertionError("watch folder check should be skipped")

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setattr(cli_service.sys, "platform", "linux")
    monkeypatch.setattr(cli_service.shutil, "which", lambda command: "/usr/local/bin/fow")
    monkeypatch.setattr(cli_service, "_has_enabled_watch_folder", fail_if_called)
    monkeypatch.setattr(cli_service, "_run_command", lambda command: calls.append(list(command)))

    result = runner.invoke(app, ["service", "install", "--start", "--force-start"])

    assert result.exit_code == 0
    assert calls[-1] == ["systemctl", "--user", "start", "fow-watch.service"]


def test_install_does_not_overwrite_existing_env_file(monkeypatch, tmp_path) -> None:
    calls = []
    env_path = tmp_path / ".config" / "fly-on-the-wall" / "service.env"
    env_path.parent.mkdir(parents=True)
    env_path.write_text("ELEVENLABS_API_KEY=existing\n", encoding="utf-8")

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setattr(cli_service.sys, "platform", "linux")
    monkeypatch.setattr(cli_service.shutil, "which", lambda command: "/usr/local/bin/fow")
    monkeypatch.setattr(cli_service, "_run_command", lambda command: calls.append(list(command)))

    result = runner.invoke(app, ["service", "install"])

    assert result.exit_code == 0
    assert env_path.read_text(encoding="utf-8") == "ELEVENLABS_API_KEY=existing\n"
    assert calls == [["systemctl", "--user", "daemon-reload"]]


def test_install_respects_xdg_config_home(monkeypatch, tmp_path) -> None:
    calls = []
    xdg_config_home = tmp_path / "xdg-config"

    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg_config_home))
    monkeypatch.setattr(cli_service.sys, "platform", "linux")
    monkeypatch.setattr(cli_service.shutil, "which", lambda command: "/usr/local/bin/fow")
    monkeypatch.setattr(cli_service, "_run_command", lambda command: calls.append(list(command)))

    result = runner.invoke(app, ["service", "install"])

    unit_path = xdg_config_home / "systemd" / "user" / "fow-watch.service"
    env_path = xdg_config_home / "fly-on-the-wall" / "service.env"
    assert result.exit_code == 0
    assert unit_path.read_text(encoding="utf-8") == cli_service.render_unit(Path("/usr/local/bin/fow"), env_path)
    assert env_path.read_text(encoding="utf-8") == cli_service.ENV_FILE_TEMPLATE
    assert calls == [["systemctl", "--user", "daemon-reload"]]


def test_uninstall_removes_existing_unit(monkeypatch, tmp_path) -> None:
    calls = []
    unit_path = tmp_path / ".config" / "systemd" / "user" / "fow-watch.service"
    unit_path.parent.mkdir(parents=True)
    unit_path.write_text("unit", encoding="utf-8")

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setattr(cli_service.sys, "platform", "linux")
    monkeypatch.setattr(cli_service, "_run_command", lambda command: calls.append(list(command)))

    result = runner.invoke(app, ["service", "uninstall"])

    assert result.exit_code == 0
    assert not unit_path.exists()
    assert calls == [
        ["systemctl", "--user", "disable", "--now", "fow-watch.service"],
        ["systemctl", "--user", "daemon-reload"],
    ]


def test_print_unit_outputs_generated_unit(monkeypatch) -> None:
    monkeypatch.setattr(cli_service.sys, "platform", "linux")
    monkeypatch.setattr(cli_service.shutil, "which", lambda command: "/usr/local/bin/fow")

    result = runner.invoke(app, ["service", "print-unit"])

    assert result.exit_code == 0
    assert "[Unit]" in result.stdout
    assert "ExecStart=/usr/local/bin/fow watch run" in result.stdout
    assert "EnvironmentFile=-" in result.stdout


@pytest.mark.parametrize(
    "arguments",
    [
        ["install"],
        ["uninstall"],
        ["start"],
        ["stop"],
        ["restart"],
        ["status"],
        ["logs"],
        ["print-unit"],
    ],
)
def test_service_commands_fail_on_unsupported_platform(monkeypatch, arguments) -> None:
    def fail_if_called(command):
        raise AssertionError(f"unexpected command: {command}")

    monkeypatch.setattr(cli_service.sys, "platform", "darwin")
    monkeypatch.setattr(cli_service, "_run_command", fail_if_called)

    result = runner.invoke(app, ["service", *arguments])

    assert result.exit_code == 1
    assert "supports Linux systemd user services" in result.stdout
    assert "only" in result.stdout


@pytest.mark.parametrize("command", ["start", "restart"])
def test_service_start_commands_refuse_without_enabled_watch_folders(monkeypatch, command) -> None:
    calls = []

    patch_no_enabled_watch_folders(monkeypatch)
    monkeypatch.setattr(cli_service, "_run_command", lambda command: calls.append(list(command)))

    result = runner.invoke(app, ["service", command])

    assert result.exit_code == 1
    assert "No enabled watch folders configured" in result.stdout
    assert calls == []


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        (["start", "--force"], ["systemctl", "--user", "start", "fow-watch.service"]),
        (["stop"], ["systemctl", "--user", "stop", "fow-watch.service"]),
        (["restart", "--force"], ["systemctl", "--user", "restart", "fow-watch.service"]),
        (["status"], ["systemctl", "--user", "--no-pager", "status", "fow-watch.service"]),
        (["logs", "--lines", "12"], ["journalctl", "--user", "-u", "fow-watch.service", "-n", "12", "--no-pager"]),
    ],
)
def test_service_command_wrappers(monkeypatch, arguments, expected) -> None:
    calls = []

    monkeypatch.setattr(cli_service.sys, "platform", "linux")
    monkeypatch.setattr(cli_service, "_run_command", lambda command: calls.append(list(command)))

    result = runner.invoke(app, ["service", *arguments])

    assert result.exit_code == 0
    assert calls == [expected]
