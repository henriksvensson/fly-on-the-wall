from pathlib import Path

from fly_on_the_wall.config import AppConfig
from fly_on_the_wall.db import database
from fly_on_the_wall.meetings import (
    file_sha256,
    import_meeting,
    latest_completed_provider_run,
    slugify,
)
from fly_on_the_wall.storage import ensure_storage_layout


def test_slugify_normalizes_titles() -> None:
    assert slugify("Intro Call With Person B!") == "intro-call-with-person_b"
    assert slugify("!!!") == "meeting"


def test_import_meeting_copies_audio_and_creates_record(tmp_path: Path) -> None:
    audio_path = tmp_path / "source.m4a"
    audio_path.write_bytes(b"fake audio")
    storage = ensure_storage_layout(tmp_path / "storage")

    with database(tmp_path / "fly.db") as connection:
        meeting = import_meeting(
            connection,
            audio_path,
            "Intro Call With Person B",
            AppConfig(language="sv"),
            storage,
            description="First call",
        )
        row = connection.execute("SELECT * FROM meetings WHERE id = ?", (meeting.id,)).fetchone()

    assert meeting.slug == "intro-call-with-person_b"
    assert meeting.imported_audio_path.read_bytes() == b"fake audio"
    assert row["title"] == "Intro Call With Person B"
    assert row["description"] == "First call"
    assert row["language"] == "sv"
    assert row["audio_sha256"] == file_sha256(audio_path)


def test_import_meeting_generates_unique_slug(tmp_path: Path) -> None:
    first_audio_path = tmp_path / "source-1.m4a"
    first_audio_path.write_bytes(b"fake audio 1")
    second_audio_path = tmp_path / "source-2.m4a"
    second_audio_path.write_bytes(b"fake audio 2")
    storage = ensure_storage_layout(tmp_path / "storage")

    with database(tmp_path / "fly.db") as connection:
        first = import_meeting(connection, first_audio_path, "Same Title", AppConfig(), storage)
        second = import_meeting(connection, second_audio_path, "Same Title", AppConfig(), storage)

    assert first.slug == "same-title"
    assert second.slug == "same-title-2"


def test_import_meeting_reuses_existing_meeting_for_same_audio_hash(tmp_path: Path) -> None:
    first_audio_path = tmp_path / "source-1.m4a"
    first_audio_path.write_bytes(b"same audio")
    second_audio_path = tmp_path / "source-2.m4a"
    second_audio_path.write_bytes(b"same audio")
    storage = ensure_storage_layout(tmp_path / "storage")

    with database(tmp_path / "fly.db") as connection:
        first = import_meeting(connection, first_audio_path, "First Title", AppConfig(), storage)
        second = import_meeting(connection, second_audio_path, "Second Title", AppConfig(), storage)
        meeting_count = connection.execute(
            "SELECT COUNT(*) AS count FROM meetings"
        ).fetchone()["count"]

    assert first.id == second.id
    assert second.title == "First Title"
    assert meeting_count == 1


def test_latest_completed_provider_run_returns_most_recent_done_run(tmp_path: Path) -> None:
    with database(tmp_path / "fly.db") as connection:
        connection.execute(
            "INSERT INTO meetings(id, slug, title, language) VALUES (?, ?, ?, ?)",
            ("meeting-1", "intro", "Intro", "sv"),
        )
        connection.execute(
            """
            INSERT INTO provider_runs(id, meeting_id, provider, model, raw_response_path, status)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("failed-run", "meeting-1", "elevenlabs", "scribe_v2", "raw.json", "failed"),
        )
        connection.execute(
            """
            INSERT INTO provider_runs(id, meeting_id, provider, model, raw_response_path, status)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("done-run", "meeting-1", "elevenlabs", "scribe_v2", "raw.json", "done"),
        )

        provider_run = latest_completed_provider_run(connection, "meeting-1")

    assert provider_run["id"] == "done-run"
