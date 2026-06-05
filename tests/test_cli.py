from contextlib import contextmanager

from typer.testing import CliRunner

import fly_on_the_wall.cli_speaker_review as cli_speaker_review
import fly_on_the_wall.setup as setup_wizard
from fly_on_the_wall.cli import app
from fly_on_the_wall.doctor import DoctorCheck
from fly_on_the_wall.secrets import SecretError

runner = CliRunner()


def test_cli_version() -> None:
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert "fly-on-the-wall 0.1.0" in result.stdout


def test_people_group_exists() -> None:
    result = runner.invoke(app, ["people", "--help"])

    assert result.exit_code == 0
    assert "Manage known people" in result.stdout


def test_setup_command_exists() -> None:
    result = runner.invoke(app, ["setup", "--help"])

    assert result.exit_code == 0
    assert "first-run setup" in result.stdout


def test_setup_can_skip_optional_configuration(monkeypatch, tmp_path) -> None:
    @contextmanager
    def fake_database():
        yield object()

    monkeypatch.setattr(
        setup_wizard,
        "run_checks",
        lambda: [
            DoctorCheck("python", True, "3.12.0"),
            DoctorCheck("ffmpeg", True, "/usr/bin/ffmpeg"),
            DoctorCheck("elevenlabs api key", False, "missing"),
        ],
    )
    monkeypatch.setattr(setup_wizard, "which", lambda command: "/usr/bin/ffmpeg")
    monkeypatch.setattr(setup_wizard, "database", fake_database)
    monkeypatch.setattr(setup_wizard, "get_user_person", lambda connection: None)
    monkeypatch.setattr(setup_wizard, "list_publish_targets", lambda connection: [])
    monkeypatch.setattr(setup_wizard, "list_watch_folders", lambda connection: [])
    monkeypatch.setattr(setup_wizard, "_module_available", lambda module_name: False)
    monkeypatch.setattr(setup_wizard, "storage_paths", lambda: type("Paths", (), {"root": tmp_path})())
    monkeypatch.setattr(
        setup_wizard,
        "get_api_key_status",
        lambda provider: type(
            "Status",
            (),
            {"available": False, "source": "missing", "env_var": f"{provider.upper()}_API_KEY"},
        )(),
    )

    result = runner.invoke(app, ["setup"], input="n\nn\nn\nn\nn\nn\n")

    assert result.exit_code == 0
    assert "Setup summary" in result.stdout
    assert "Required setup: incomplete" in result.stdout


def test_secrets_set_prints_env_fallback_when_keyring_fails(monkeypatch) -> None:
    monkeypatch.setattr(
        "fly_on_the_wall.cli.set_api_key",
        lambda provider, value: (_ for _ in ()).throw(SecretError("keyring failed")),
    )

    result = runner.invoke(app, ["secrets", "set", "openai"], input="dummy\n")

    assert result.exit_code != 0
    assert "Alternative: set OPENAI_API_KEY" in result.stdout


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


def test_meetings_remove_asks_about_published_notes(monkeypatch) -> None:
    @contextmanager
    def fake_database():
        yield object()

    captured = {}

    def fake_delete_meeting(connection, meeting, delete_published=False):
        captured["delete_published"] = delete_published
        return type("Result", (), {"slug": "intro", "removed_paths": ()})()

    monkeypatch.setattr("fly_on_the_wall.cli.database", fake_database)
    monkeypatch.setattr(
        "fly_on_the_wall.cli.get_meeting",
        lambda connection, meeting: {"id": "meeting-1", "slug": "intro"},
    )
    monkeypatch.setattr("fly_on_the_wall.cli._meeting_has_published_items", lambda connection, meeting_id: True)
    monkeypatch.setattr("fly_on_the_wall.cli.delete_meeting", fake_delete_meeting)

    result = runner.invoke(app, ["meetings", "remove", "intro"], input="y\ny\n")

    assert result.exit_code == 0
    assert "Delete externally published notes" in result.stdout
    assert captured["delete_published"] is True


def test_meetings_remove_yes_does_not_prompt_about_published_notes(monkeypatch) -> None:
    @contextmanager
    def fake_database():
        yield object()

    captured = {}

    def fake_delete_meeting(connection, meeting, delete_published=False):
        captured["delete_published"] = delete_published
        return type("Result", (), {"slug": "intro", "removed_paths": ()})()

    monkeypatch.setattr("fly_on_the_wall.cli.database", fake_database)
    monkeypatch.setattr(
        "fly_on_the_wall.cli.get_meeting",
        lambda connection, meeting: {"id": "meeting-1", "slug": "intro"},
    )
    monkeypatch.setattr(
        "fly_on_the_wall.cli._meeting_has_published_items",
        lambda connection, meeting_id: (_ for _ in ()).throw(AssertionError("should not check published items")),
    )
    monkeypatch.setattr("fly_on_the_wall.cli.delete_meeting", fake_delete_meeting)

    result = runner.invoke(app, ["meetings", "remove", "intro", "--yes"])

    assert result.exit_code == 0
    assert "Delete externally published notes" not in result.stdout
    assert captured["delete_published"] is False


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
    assert "unknown or uncertain meeting speakers" in result.stdout
    assert "include-uncertain" in result.stdout
    assert "only-uncertain" in result.stdout


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

    monkeypatch.setattr(cli_speaker_review, "database", fake_database)
    monkeypatch.setattr(
        cli_speaker_review,
        "list_review_speakers",
        lambda connection, meeting=None, include_uncertain=False, only_uncertain=False: speakers,
    )
    monkeypatch.setattr(cli_speaker_review, "speaker_examples", lambda connection, speaker_id, limit=1: [])
    monkeypatch.setattr(cli_speaker_review, "prepare_speaker_review_clip", lambda connection, speaker_id: None)
    monkeypatch.setattr(cli_speaker_review, "mark_speaker_ignored", lambda connection, speaker_id: None)
    monkeypatch.setattr(
        cli_speaker_review,
        "_select_speaker_review_action",
        lambda clip_available, can_confirm=False: next(actions),
    )
    monkeypatch.setattr(cli_speaker_review, "_select_speaker_review_follow_up_action", lambda: "n")

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

    monkeypatch.setattr(cli_speaker_review, "database", fake_database)
    monkeypatch.setattr(
        cli_speaker_review,
        "list_review_speakers",
        lambda connection, meeting=None, include_uncertain=False, only_uncertain=False: speakers,
    )
    monkeypatch.setattr(cli_speaker_review, "speaker_examples", lambda connection, speaker_id, limit=1: [])
    monkeypatch.setattr(cli_speaker_review, "prepare_speaker_review_clip", lambda connection, speaker_id: None)
    monkeypatch.setattr(cli_speaker_review, "_select_speaker_review_action", lambda clip_path, can_confirm=False: "o")
    monkeypatch.setattr(cli_speaker_review.typer, "prompt", lambda *args, **kwargs: "Person A")
    monkeypatch.setattr(
        cli_speaker_review,
        "assign_speaker_to_person",
        lambda connection, speaker_id, person: {"name": person},
    )
    monkeypatch.setattr(cli_speaker_review, "_speaker_review_follow_up", lambda connection, changed: set())

    result = runner.invoke(app, ["meetings", "speakers", "review"])

    assert result.exit_code == 0
    assert "Created known person Person A" in result.stdout
    assert "without voice sample" in result.stdout


def test_speakers_review_can_confirm_uncertain_suggestion(monkeypatch) -> None:
    @contextmanager
    def fake_database():
        yield object()

    speakers = [
        {
            "id": "speaker-1",
            "meeting_slug": "intro",
            "label": "speaker_0",
            "review_kind": "uncertain",
            "suggested_person_id": "person-1",
            "suggested_person_name": "Person A",
            "confidence": 0.73,
            "margin": 0.11,
        }
    ]

    monkeypatch.setattr(cli_speaker_review, "database", fake_database)
    monkeypatch.setattr(
        cli_speaker_review,
        "list_review_speakers",
        lambda connection, meeting=None, include_uncertain=False, only_uncertain=False: speakers,
    )
    monkeypatch.setattr(cli_speaker_review, "speaker_examples", lambda connection, speaker_id, limit=1: [])
    monkeypatch.setattr(cli_speaker_review, "prepare_speaker_review_clip", lambda connection, speaker_id: None)
    monkeypatch.setattr(cli_speaker_review, "_select_speaker_review_action", lambda clip_path, can_confirm=False: "v")
    monkeypatch.setattr(cli_speaker_review, "_try_embedding_backend", lambda: None)
    monkeypatch.setattr(
        cli_speaker_review,
        "create_voice_identity_from_speaker",
        lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("no timestamped audio")),
    )
    monkeypatch.setattr(
        cli_speaker_review,
        "confirm_speaker_assignment",
        lambda connection, speaker_id: {"name": "Person A"},
    )
    monkeypatch.setattr(cli_speaker_review, "_speaker_review_follow_up", lambda connection, changed: set())

    result = runner.invoke(app, ["meetings", "speakers", "review", "--only-uncertain"])

    assert result.exit_code == 0
    assert "Suggested person: Person A" in result.stdout
    assert "Confirmed meeting speaker as Person A" in result.stdout


def test_speaker_review_follow_up_can_reanalyze_unknown_speakers(monkeypatch) -> None:
    monkeypatch.setattr(cli_speaker_review, "_select_speaker_review_follow_up_action", lambda: "g")
    monkeypatch.setattr(
        cli_speaker_review,
        "rerun_speaker_matching_for_meetings",
        lambda connection: [{"meeting_slug": "other", "match_count": 1}],
    )

    refresh_meetings = cli_speaker_review._speaker_review_follow_up(object(), {"intro"})

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


def test_costs_group_exists() -> None:
    result = runner.invoke(app, ["costs", "--help"])

    assert result.exit_code == 0
    assert "service usage" in result.stdout


def test_costs_summary_command_exists() -> None:
    result = runner.invoke(app, ["costs", "summary", "--help"])

    assert result.exit_code == 0
    assert "estimated external service costs" in result.stdout


def test_costs_meeting_command_exists() -> None:
    result = runner.invoke(app, ["costs", "meeting", "--help"])

    assert result.exit_code == 0
    assert "one meeting" in result.stdout


def test_watch_run_command_is_event_driven() -> None:
    result = runner.invoke(app, ["watch", "run", "--help"])

    assert result.exit_code == 0
    assert "Watch enabled folders" in result.stdout
    assert "interval-seconds" in result.stdout
