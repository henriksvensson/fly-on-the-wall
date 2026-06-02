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
