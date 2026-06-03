from pathlib import Path
from types import SimpleNamespace

from fly_on_the_wall.config import AppConfig
from fly_on_the_wall.db import database
from fly_on_the_wall.meetings import file_sha256
from fly_on_the_wall.watch import (
    DEFAULT_STABLE_AGE_SECONDS,
    add_watch_folder,
    list_watch_folders,
    remove_watch_folder,
    scan_watch_folders,
    set_watch_folder_enabled,
)


def test_default_stable_age_is_five_seconds() -> None:
    assert DEFAULT_STABLE_AGE_SECONDS == 5


def test_watch_folder_crud(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()

    with database(tmp_path / "fly.db") as connection:
        folder = add_watch_folder(connection, inbox, name="dropbox")
        folders = list_watch_folders(connection)
        disabled = set_watch_folder_enabled(connection, "dropbox", False)
        removed = remove_watch_folder(connection, folder.id)

    assert folders == [folder]
    assert disabled is not None
    assert not disabled.enabled
    assert removed is not None
    assert removed.id == folder.id


def test_scan_processes_stable_audio_file(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    audio_path = inbox / "Team Sync.m4a"
    audio_path.write_bytes(b"audio")
    calls = []

    def fake_process(connection, path, title, config, storage=None, progress=None):
        calls.append((path, title, config, storage))
        connection.execute(
            "INSERT INTO meetings(id, slug, title, language) VALUES (?, ?, ?, ?)",
            ("meeting-1", "team-sync", "Team Sync", "sv"),
        )
        return SimpleNamespace(meeting=SimpleNamespace(id="meeting-1"))

    with database(tmp_path / "fly.db") as connection:
        add_watch_folder(connection, inbox)
        result = scan_watch_folders(
            connection,
            AppConfig(),
            process_fn=fake_process,
            stable_age_seconds=0,
        )
        item = connection.execute(
            "SELECT * FROM watch_items WHERE path = ?", (str(audio_path),)
        ).fetchone()

    assert result.seen == 1
    assert result.processed == 1
    assert calls[0][0] == audio_path
    assert calls[0][1] == "Team Sync"
    assert item["status"] == "done"
    assert item["meeting_id"] == "meeting-1"
    assert item["file_sha256"] == file_sha256(audio_path)


def test_scan_skips_done_item_for_unchanged_file(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    audio_path = inbox / "meeting.mp3"
    audio_path.write_bytes(b"audio")
    calls = []

    def fake_process(connection, path, title, config, storage=None, progress=None):
        calls.append(path)
        connection.execute(
            "INSERT INTO meetings(id, slug, title, language) VALUES (?, ?, ?, ?)",
            ("meeting-1", "meeting", "Meeting", "sv"),
        )
        return SimpleNamespace(meeting=SimpleNamespace(id="meeting-1"))

    with database(tmp_path / "fly.db") as connection:
        add_watch_folder(connection, inbox)
        scan_watch_folders(connection, AppConfig(), process_fn=fake_process, stable_age_seconds=0)
        result = scan_watch_folders(
            connection, AppConfig(), process_fn=fake_process, stable_age_seconds=0
        )

    assert result.processed == 0
    assert result.skipped == 1
    assert calls == [audio_path]


def test_scan_skips_recently_modified_audio_file(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    audio_path = inbox / "meeting.wav"
    audio_path.write_bytes(b"audio")

    def fake_process(connection, path, title, config, storage=None, progress=None):
        raise AssertionError("recent files should not be processed")

    with database(tmp_path / "fly.db") as connection:
        add_watch_folder(connection, inbox)
        result = scan_watch_folders(
            connection,
            AppConfig(),
            process_fn=fake_process,
            stable_age_seconds=3600,
        )
        item = connection.execute(
            "SELECT * FROM watch_items WHERE path = ?", (str(audio_path),)
        ).fetchone()

    assert result.processed == 0
    assert result.skipped == 1
    assert item["status"] == "pending"


def test_scan_records_processing_failures(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    audio_path = inbox / "meeting.caf"
    audio_path.write_bytes(b"audio")

    def fake_process(connection, path, title, config, storage=None, progress=None):
        raise RuntimeError("provider unavailable")

    with database(tmp_path / "fly.db") as connection:
        add_watch_folder(connection, inbox)
        result = scan_watch_folders(
            connection,
            AppConfig(),
            process_fn=fake_process,
            stable_age_seconds=0,
        )
        item = connection.execute(
            "SELECT * FROM watch_items WHERE path = ?", (str(audio_path),)
        ).fetchone()

    assert result.failed == 1
    assert item["status"] == "failed"
    assert item["error_message"] == "provider unavailable"
