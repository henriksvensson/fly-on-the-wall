from contextlib import contextmanager

from typer.testing import CliRunner

import fly_on_the_wall.cli as cli
from fly_on_the_wall.cli import app

runner = CliRunner()


def test_cli_version() -> None:
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert "fly-on-the-wall 0.1.0" in result.stdout


def test_people_group_exists() -> None:
    result = runner.invoke(app, ["people", "--help"])

    assert result.exit_code == 0
    assert "Manage known people" in result.stdout


def test_people_set_user_command_exists() -> None:
    result = runner.invoke(app, ["people", "set-user", "--help"])

    assert result.exit_code == 0
    assert "system user" in result.stdout


def test_people_show_user_command_exists() -> None:
    result = runner.invoke(app, ["people", "show-user", "--help"])

    assert result.exit_code == 0
    assert "system user" in result.stdout


def test_people_unset_user_command_exists() -> None:
    result = runner.invoke(app, ["people", "unset-user", "--help"])

    assert result.exit_code == 0
    assert "system user" in result.stdout


def test_people_embeddings_group_exists() -> None:
    result = runner.invoke(app, ["people", "embeddings", "--help"])

    assert result.exit_code == 0
    assert "voice embeddings" in result.stdout


def test_people_embeddings_status_command_exists() -> None:
    result = runner.invoke(app, ["people", "embeddings", "status", "--help"])

    assert result.exit_code == 0
    assert "embedding coverage" in result.stdout


def test_people_embeddings_backfill_command_exists() -> None:
    result = runner.invoke(app, ["people", "embeddings", "backfill", "--help"])

    assert result.exit_code == 0
    assert "missing voice embeddings" in result.stdout


def test_meetings_group_exists() -> None:
    result = runner.invoke(app, ["meetings", "--help"])

    assert result.exit_code == 0
    assert "Inspect meetings" in result.stdout


def test_meetings_remove_command_exists() -> None:
    result = runner.invoke(app, ["meetings", "remove", "--help"])

    assert result.exit_code == 0
    assert "Completely remove a meeting" in result.stdout


def test_meetings_rename_command_exists() -> None:
    result = runner.invoke(app, ["meetings", "rename", "--help"])

    assert result.exit_code == 0
    assert "Manually rename a meeting" in result.stdout


def test_meetings_status_command_exists() -> None:
    result = runner.invoke(app, ["meetings", "status", "--help"])

    assert result.exit_code == 0
    assert "pipeline status" in result.stdout


def test_meetings_speakers_group_exists() -> None:
    result = runner.invoke(app, ["meetings", "speakers", "--help"])

    assert result.exit_code == 0
    assert "meeting-local speakers" in result.stdout


def test_meetings_speakers_review_command_exists() -> None:
    result = runner.invoke(app, ["meetings", "speakers", "review", "--help"])

    assert result.exit_code == 0
    assert "unknown meeting speakers" in result.stdout


def test_meetings_speakers_ignore_command_exists() -> None:
    result = runner.invoke(app, ["meetings", "speakers", "ignore", "--help"])

    assert result.exit_code == 0
    assert "not shown during review" in result.stdout


def test_refresh_group_exists() -> None:
    result = runner.invoke(app, ["refresh", "--help"])

    assert result.exit_code == 0
    assert "Refresh derived meeting outputs" in result.stdout


def test_refresh_speakers_supports_include_known_flag() -> None:
    result = runner.invoke(app, ["refresh", "speakers", "--help"])

    assert result.exit_code == 0
    assert "include-known-speakers" in result.stdout


def test_refresh_stale_meetings_command_exists() -> None:
    result = runner.invoke(app, ["refresh", "stale-meetings", "--help"])

    assert result.exit_code == 0
    assert "stale derived outputs" in result.stdout


def test_refresh_meeting_command_exists() -> None:
    result = runner.invoke(app, ["refresh", "meeting", "--help"])

    assert result.exit_code == 0
    assert "one meeting" in result.stdout


def test_speakers_review_quit_still_prompts_for_refresh(monkeypatch) -> None:
    @contextmanager
    def fake_database():
        yield object()

    speakers = [
        {"id": "speaker-1", "meeting_slug": "intro", "label": "speaker_0"},
        {"id": "speaker-2", "meeting_slug": "intro", "label": "speaker_1"},
    ]
    actions = iter(["i", "q"])

    monkeypatch.setattr(cli, "database", fake_database)
    monkeypatch.setattr(cli, "list_unknown_speakers", lambda connection, meeting=None: speakers)
    monkeypatch.setattr(cli, "speaker_examples", lambda connection, speaker_id, limit=1: [])
    monkeypatch.setattr(cli, "prepare_speaker_review_clip", lambda connection, speaker_id: None)
    monkeypatch.setattr(cli, "mark_speaker_ignored", lambda connection, speaker_id: None)
    monkeypatch.setattr(cli, "_select_speaker_review_action", lambda clip_available: next(actions))
    monkeypatch.setattr(cli, "_select_speaker_review_follow_up_action", lambda: "n")

    result = runner.invoke(app, ["meetings", "speakers", "review"])

    assert result.exit_code == 0
    assert "Review cancelled." in result.stdout
    assert "Speaker review changed 1 meeting(s)." in result.stdout
    assert "Refresh skipped." in result.stdout


def test_speakers_review_can_create_new_person_without_voice_sample(monkeypatch) -> None:
    @contextmanager
    def fake_database():
        yield object()

    speakers = [{"id": "speaker-1", "meeting_slug": "intro", "label": "speaker_0"}]

    monkeypatch.setattr(cli, "database", fake_database)
    monkeypatch.setattr(cli, "list_unknown_speakers", lambda connection, meeting=None: speakers)
    monkeypatch.setattr(cli, "speaker_examples", lambda connection, speaker_id, limit=1: [])
    monkeypatch.setattr(cli, "prepare_speaker_review_clip", lambda connection, speaker_id: None)
    monkeypatch.setattr(cli, "_select_speaker_review_action", lambda clip_path: "o")
    monkeypatch.setattr(cli.typer, "prompt", lambda *args, **kwargs: "Person B")
    monkeypatch.setattr(
        cli,
        "assign_speaker_to_person",
        lambda connection, speaker_id, person: {"name": person},
    )
    monkeypatch.setattr(cli, "_speaker_review_follow_up", lambda connection, changed: set())

    result = runner.invoke(app, ["meetings", "speakers", "review"])

    assert result.exit_code == 0
    assert "Created known person Person B" in result.stdout
    assert "without voice sample" in result.stdout


def test_speaker_review_follow_up_can_reanalyze_unknown_speakers(monkeypatch) -> None:
    monkeypatch.setattr(cli, "_select_speaker_review_follow_up_action", lambda: "g")
    monkeypatch.setattr(
        cli,
        "rerun_speaker_matching_for_meetings",
        lambda connection: [{"meeting_slug": "other", "match_count": 1}],
    )

    refresh_meetings = cli._speaker_review_follow_up(object(), {"intro"})

    assert refresh_meetings == {"intro", "other"}


def test_secrets_group_exists() -> None:
    result = runner.invoke(app, ["secrets", "--help"])

    assert result.exit_code == 0
    assert "Manage API keys in the OS keyring" in result.stdout


def test_watch_group_exists() -> None:
    result = runner.invoke(app, ["watch", "--help"])

    assert result.exit_code == 0
    assert "Process audio from watched folders" in result.stdout


def test_watch_folders_group_exists() -> None:
    result = runner.invoke(app, ["watch", "folders", "--help"])

    assert result.exit_code == 0
    assert "Manage watched folders" in result.stdout


def test_watch_scan_command_exists() -> None:
    result = runner.invoke(app, ["watch", "scan", "--help"])

    assert result.exit_code == 0
    assert "Scan enabled watched folders" in result.stdout


def test_publish_group_exists() -> None:
    result = runner.invoke(app, ["publish", "--help"])

    assert result.exit_code == 0
    assert "Publish meetings to external targets" in result.stdout


def test_publish_targets_group_exists() -> None:
    result = runner.invoke(app, ["publish", "targets", "--help"])

    assert result.exit_code == 0
    assert "Manage publish targets" in result.stdout


def test_publish_meeting_command_exists() -> None:
    result = runner.invoke(app, ["publish", "meeting", "--help"])

    assert result.exit_code == 0
    assert "Publish one meeting" in result.stdout


def test_publish_all_command_exists() -> None:
    result = runner.invoke(app, ["publish", "all", "--help"])

    assert result.exit_code == 0
    assert "Publish all exported meetings" in result.stdout


def test_watch_run_command_is_event_driven() -> None:
    result = runner.invoke(app, ["watch", "run", "--help"])

    assert result.exit_code == 0
    assert "Watch enabled folders" in result.stdout
    assert "interval-seconds" in result.stdout
