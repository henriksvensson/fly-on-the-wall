from pathlib import Path

from fly_on_the_wall.config import AppConfig
from fly_on_the_wall.db import database
from fly_on_the_wall.meetings import import_meeting, slugify
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


def test_import_meeting_generates_unique_slug(tmp_path: Path) -> None:
    audio_path = tmp_path / "source.m4a"
    audio_path.write_bytes(b"fake audio")
    storage = ensure_storage_layout(tmp_path / "storage")

    with database(tmp_path / "fly.db") as connection:
        first = import_meeting(connection, audio_path, "Same Title", AppConfig(), storage)
        second = import_meeting(connection, audio_path, "Same Title", AppConfig(), storage)

    assert first.slug == "same-title"
    assert second.slug == "same-title-2"
