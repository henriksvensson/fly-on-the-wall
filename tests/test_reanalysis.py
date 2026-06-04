from fly_on_the_wall.db import database
from fly_on_the_wall.reanalysis import (
    list_stale_meetings,
    list_stale_stages,
    mark_speaker_reanalysis_stale,
    rerun_speaker_matching_for_meetings,
)


def test_mark_speaker_reanalysis_stale_marks_downstream_stages(tmp_path) -> None:
    with database(tmp_path / "fly.db") as connection:
        connection.execute(
            "INSERT INTO meetings(id, slug, title, language) VALUES (?, ?, ?, ?)",
            ("meeting-1", "intro", "Intro", "sv"),
        )
        stages = mark_speaker_reanalysis_stale(connection, "intro")
        stale = list_stale_stages(connection)

    assert stages == ["speaker_matching", "render", "cleanup", "export"]
    assert {row["stage_name"] for row in stale} == set(stages)


def test_list_stale_meetings_deduplicates_meetings(tmp_path) -> None:
    with database(tmp_path / "fly.db") as connection:
        connection.execute(
            "INSERT INTO meetings(id, slug, title, language) VALUES (?, ?, ?, ?)",
            ("meeting-1", "intro", "Intro", "sv"),
        )
        mark_speaker_reanalysis_stale(connection, "intro")

        stale_meetings = list_stale_meetings(connection)

    assert stale_meetings == [{"meeting_id": "meeting-1", "meeting_slug": "intro"}]


def test_rerun_speaker_matching_defaults_to_unknown_speaker_meetings(tmp_path, monkeypatch) -> None:
    matched_provider_runs = []

    def fake_match(connection, provider_run_id, *args, **kwargs):
        matched_provider_runs.append(provider_run_id)
        return [object()]

    monkeypatch.setattr("fly_on_the_wall.reanalysis.match_provider_run_speakers", fake_match)

    with database(tmp_path / "fly.db") as connection:
        _insert_meeting_with_speaker(connection, "unknown-meeting", assignment_status=None)
        _insert_meeting_with_speaker(connection, "known-meeting", assignment_status="known")

        results = rerun_speaker_matching_for_meetings(connection)

    assert [result["meeting_slug"] for result in results] == ["unknown-meeting"]
    assert matched_provider_runs == ["run-unknown-meeting"]
    assert results[0]["match_count"] == 0
    assert results[0]["marked_stale"] == []


def test_rerun_speaker_matching_reports_progress(tmp_path, monkeypatch) -> None:
    messages = []

    def fake_match(connection, provider_run_id, *args, **kwargs):
        return []

    monkeypatch.setattr("fly_on_the_wall.reanalysis.match_provider_run_speakers", fake_match)

    with database(tmp_path / "fly.db") as connection:
        _insert_meeting_with_speaker(connection, "unknown-meeting", assignment_status=None)

        rerun_speaker_matching_for_meetings(connection, progress=messages.append)

    assert messages == [
        "Found 1 meeting(s) for speaker refresh",
        "Refreshing speaker matching for unknown-meeting (1/1)",
        "Embedding and matching speakers for unknown-meeting",
        "unknown-meeting: 0 speaker assignment change(s)",
    ]


def test_rerun_speaker_matching_marks_stale_only_when_assignments_change(tmp_path, monkeypatch) -> None:
    def fake_match(connection, provider_run_id, *args, **kwargs):
        connection.execute(
            """
            INSERT INTO speaker_assignments(id, local_speaker_id, person_id, status)
            VALUES (?, ?, ?, ?)
            """,
            ("assignment-1", "speaker-unknown-meeting", None, "unknown"),
        )
        return []

    monkeypatch.setattr("fly_on_the_wall.reanalysis.match_provider_run_speakers", fake_match)

    with database(tmp_path / "fly.db") as connection:
        _insert_meeting_with_speaker(connection, "unknown-meeting", assignment_status=None)

        results = rerun_speaker_matching_for_meetings(connection)
        stale = list_stale_stages(connection)

    assert results[0]["match_count"] == 1
    assert results[0]["marked_stale"] == ["speaker_matching", "render", "cleanup", "export"]
    assert {row["stage_name"] for row in stale} == set(results[0]["marked_stale"])


def test_rerun_speaker_matching_can_include_known_speaker_meetings(tmp_path, monkeypatch) -> None:
    matched_provider_runs = []

    def fake_match(connection, provider_run_id, *args, **kwargs):
        matched_provider_runs.append(provider_run_id)
        return []

    monkeypatch.setattr("fly_on_the_wall.reanalysis.match_provider_run_speakers", fake_match)

    with database(tmp_path / "fly.db") as connection:
        _insert_meeting_with_speaker(connection, "unknown-meeting", assignment_status=None)
        _insert_meeting_with_speaker(connection, "known-meeting", assignment_status="known")

        results = rerun_speaker_matching_for_meetings(connection, include_known_speakers=True)

    assert {result["meeting_slug"] for result in results} == {
        "unknown-meeting",
        "known-meeting",
    }
    assert set(matched_provider_runs) == {"run-unknown-meeting", "run-known-meeting"}


def _insert_meeting_with_speaker(connection, slug: str, assignment_status: str | None) -> None:
    connection.execute(
        "INSERT INTO meetings(id, slug, title, language) VALUES (?, ?, ?, ?)",
        (f"meeting-{slug}", slug, slug, "sv"),
    )
    connection.execute(
        """
        INSERT INTO provider_runs(id, meeting_id, provider, model, status)
        VALUES (?, ?, ?, ?, ?)
        """,
        (f"run-{slug}", f"meeting-{slug}", "elevenlabs", "scribe_v2", "done"),
    )
    connection.execute(
        """
        INSERT INTO local_speakers(id, meeting_id, provider_run_id, label)
        VALUES (?, ?, ?, ?)
        """,
        (f"speaker-{slug}", f"meeting-{slug}", f"run-{slug}", "speaker_0"),
    )
    if assignment_status is not None:
        connection.execute(
            "INSERT INTO people(id, display_name) VALUES (?, ?)",
            (f"person-{slug}", f"Person {slug}"),
        )
        connection.execute(
            """
            INSERT INTO speaker_assignments(id, local_speaker_id, person_id, status)
            VALUES (?, ?, ?, ?)
            """,
            (
                f"assignment-{slug}",
                f"speaker-{slug}",
                f"person-{slug}",
                assignment_status,
            ),
        )
