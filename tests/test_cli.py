from typer.testing import CliRunner

from fly_on_the_wall.cli import app

runner = CliRunner()


def test_cli_hello() -> None:
    result = runner.invoke(app, ["hello"])

    assert result.exit_code == 0
    assert "Fly on the Wall CLI is ready." in result.stdout


def test_cli_version() -> None:
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert "fly-on-the-wall 0.1.0" in result.stdout


def test_people_group_exists() -> None:
    result = runner.invoke(app, ["people", "--help"])

    assert result.exit_code == 0
    assert "Manage known people" in result.stdout


def test_meetings_group_exists() -> None:
    result = runner.invoke(app, ["meetings", "--help"])

    assert result.exit_code == 0
    assert "Inspect meetings" in result.stdout


def test_speakers_group_exists() -> None:
    result = runner.invoke(app, ["speakers", "--help"])

    assert result.exit_code == 0
    assert "Review and assign speakers" in result.stdout


def test_speakers_review_command_exists() -> None:
    result = runner.invoke(app, ["speakers", "review", "--help"])

    assert result.exit_code == 0
    assert "Interactively review unknown speakers" in result.stdout


def test_secrets_group_exists() -> None:
    result = runner.invoke(app, ["secrets", "--help"])

    assert result.exit_code == 0
    assert "Manage API keys in the OS keyring" in result.stdout
