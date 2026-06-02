from fly_on_the_wall.doctor import DoctorCheck, check_names, has_failures, run_checks


def test_has_failures_detects_failed_checks() -> None:
    checks = [DoctorCheck("ok", True, ""), DoctorCheck("bad", False, "")]

    assert has_failures(checks) is True


def test_has_failures_accepts_all_ok_checks() -> None:
    checks = [DoctorCheck("ok", True, "")]

    assert has_failures(checks) is False


def test_run_checks_includes_core_checks(monkeypatch) -> None:
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-elevenlabs")
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai")

    checks = run_checks()

    assert {"python", "ffmpeg", "config path", "storage path"} <= check_names(checks)


def test_doctor_cli_reports_missing_key_without_secret(monkeypatch) -> None:
    from typer.testing import CliRunner

    from fly_on_the_wall.cli import app

    monkeypatch.setenv("ELEVENLABS_API_KEY", "secret-value")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-secret")

    result = CliRunner().invoke(app, ["doctor"])

    assert "secret-value" not in result.stdout
    assert "openai-secret" not in result.stdout
