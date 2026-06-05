from fly_on_the_wall.db import database
from fly_on_the_wall.speakers import (
    confirm_speaker_assignment,
    list_review_speakers,
    list_uncertain_speakers,
    list_unknown_speakers,
    mark_speaker_ignored,
)


def test_list_unknown_speakers_returns_unassigned_local_speakers(tmp_path) -> None:
    with database(tmp_path / "fly.db") as connection:
        _insert_unknown_fixture(connection)
        unknown = list_unknown_speakers(connection, "intro")

    assert len(unknown) == 1
    assert unknown[0]["id"] == "local-1"
    assert unknown[0]["segment_count"] == 1


def test_list_unknown_speakers_excludes_ignored_local_speakers(tmp_path) -> None:
    with database(tmp_path / "fly.db") as connection:
        _insert_unknown_fixture(connection)
        mark_speaker_ignored(connection, "local-1")

        unknown = list_unknown_speakers(connection, "intro")
        assignment = connection.execute("SELECT status FROM speaker_assignments").fetchone()

    assert unknown == []
    assert assignment["status"] == "ignored"


def test_list_uncertain_speakers_returns_suggestions(tmp_path) -> None:
    with database(tmp_path / "fly.db") as connection:
        _insert_unknown_fixture(connection)
        _insert_uncertain_assignment(connection)

        uncertain = list_uncertain_speakers(connection, "intro")
        review = list_review_speakers(connection, "intro", include_uncertain=True)

    assert len(uncertain) == 1
    assert uncertain[0]["id"] == "local-1"
    assert uncertain[0]["suggested_person_name"] == "Person B"
    assert uncertain[0]["confidence"] == 0.73
    assert [speaker["review_kind"] for speaker in review] == ["uncertain"]


def test_confirm_speaker_assignment_promotes_uncertain_match(tmp_path) -> None:
    with database(tmp_path / "fly.db") as connection:
        _insert_unknown_fixture(connection)
        _insert_uncertain_assignment(connection)

        confirmed = confirm_speaker_assignment(connection, "local-1")
        assignment = connection.execute("SELECT status, person_id FROM speaker_assignments").fetchone()

    assert confirmed["name"] == "Person B"
    assert assignment["status"] == "known"
    assert assignment["person_id"] == "person-1"


def _insert_unknown_fixture(connection) -> None:
    connection.execute(
        "INSERT INTO meetings(id, slug, title, language) VALUES (?, ?, ?, ?)",
        ("meeting-1", "intro", "Intro", "sv"),
    )
    connection.execute(
        """
        INSERT INTO provider_runs(id, meeting_id, provider, model, raw_response_path, status)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        ("run-1", "meeting-1", "elevenlabs", "scribe_v2", "raw.json", "done"),
    )
    connection.execute(
        """
        INSERT INTO local_speakers(id, meeting_id, provider_run_id, label)
        VALUES (?, ?, ?, ?)
        """,
        ("local-1", "meeting-1", "run-1", "speaker_0"),
    )
    connection.execute(
        """
        INSERT INTO segments(id, meeting_id, provider_run_id, local_speaker_id, sequence, text)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        ("segment-1", "meeting-1", "run-1", "local-1", 0, "Hej"),
    )


def _insert_uncertain_assignment(connection) -> None:
    connection.execute(
        "INSERT INTO people(id, display_name) VALUES (?, ?)",
        ("person-1", "Person B"),
    )
    connection.execute(
        """
        INSERT INTO speaker_assignments(
            id, local_speaker_id, person_id, status, confidence, margin, evidence_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        ("assignment-1", "local-1", "person-1", "uncertain", 0.73, 0.11, "{}"),
    )
