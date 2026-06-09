import os
import time
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
    set_watch_folder_delete_originals_after_import,
    set_watch_folder_enabled,
)


def test_default_stable_age_is_five_seconds() -> None:
    assert DEFAULT_STABLE_AGE_SECONDS == 5


def test_watch_folder_crud(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()

    with database(tmp_path / "fly.db") as connection:
        folder = add_watch_folder(connection, inbox, name="dropbox", delete_originals_after_import=True)
        folders = list_watch_folders(connection)
        disabled = set_watch_folder_enabled(connection, "dropbox", False)
        kept = set_watch_folder_delete_originals_after_import(connection, "dropbox", False)
        removed = remove_watch_folder(connection, folder.id)

    assert folders == [folder]
    assert disabled is not None
    assert not disabled.enabled
    assert disabled.delete_originals_after_import
    assert kept is not None
    assert not kept.delete_originals_after_import
    assert removed is not None
    assert removed.id == folder.id


def test_can_add_watch_folder_before_it_exists(tmp_path: Path) -> None:
    removable_path = tmp_path / "PHILIPS"

    with database(tmp_path / "fly.db") as connection:
        folder = add_watch_folder(connection, removable_path, name="recorder")

    assert folder.path == removable_path
    assert folder.enabled


def test_scan_skips_missing_watch_folder(tmp_path: Path) -> None:
    removable_path = tmp_path / "PHILIPS"
    messages: list[str] = []

    with database(tmp_path / "fly.db") as connection:
        add_watch_folder(connection, removable_path, name="recorder")
        result = scan_watch_folders(connection, AppConfig(), progress=messages.append)

    assert result.seen == 0
    assert result.processed == 0
    assert messages == [f"Skipping missing folder {removable_path}"]


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
        item = connection.execute("SELECT * FROM watch_items WHERE path = ?", (str(audio_path),)).fetchone()

    assert result.seen == 1
    assert result.processed == 1
    assert calls[0][0] == audio_path
    assert calls[0][1] is None
    assert item["status"] == "done"
    assert item["meeting_id"] == "meeting-1"
    assert item["file_sha256"] == file_sha256(audio_path)


def test_scan_deletes_original_for_configured_watch_folder_after_success(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    audio_path = inbox / "meeting.mp3"
    imported_audio_path = tmp_path / "stored" / "meeting.mp3"
    imported_audio_path.parent.mkdir()
    imported_audio_path.write_bytes(b"audio")
    audio_path.write_bytes(b"audio")
    messages: list[str] = []

    def fake_process(connection, path, title, config, storage=None, progress=None):
        connection.execute(
            "INSERT INTO meetings(id, slug, title, language) VALUES (?, ?, ?, ?)",
            ("meeting-1", "meeting", "Meeting", "sv"),
        )
        return SimpleNamespace(meeting=SimpleNamespace(id="meeting-1", imported_audio_path=imported_audio_path))

    with database(tmp_path / "fly.db") as connection:
        add_watch_folder(connection, inbox, delete_originals_after_import=True)
        result = scan_watch_folders(
            connection,
            AppConfig(),
            process_fn=fake_process,
            stable_age_seconds=0,
            progress=messages.append,
        )

    assert result.processed == 1
    assert not audio_path.exists()
    assert imported_audio_path.exists()
    assert messages[-1] == f"Deleted original audio file {audio_path}"


def test_scan_keeps_original_for_default_watch_folder_after_success(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    audio_path = inbox / "meeting.mp3"
    imported_audio_path = tmp_path / "stored" / "meeting.mp3"
    imported_audio_path.parent.mkdir()
    imported_audio_path.write_bytes(b"audio")
    audio_path.write_bytes(b"audio")

    def fake_process(connection, path, title, config, storage=None, progress=None):
        connection.execute(
            "INSERT INTO meetings(id, slug, title, language) VALUES (?, ?, ?, ?)",
            ("meeting-1", "meeting", "Meeting", "sv"),
        )
        return SimpleNamespace(meeting=SimpleNamespace(id="meeting-1", imported_audio_path=imported_audio_path))

    with database(tmp_path / "fly.db") as connection:
        add_watch_folder(connection, inbox)
        result = scan_watch_folders(connection, AppConfig(), process_fn=fake_process, stable_age_seconds=0)

    assert result.processed == 1
    assert audio_path.exists()


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
        result = scan_watch_folders(connection, AppConfig(), process_fn=fake_process, stable_age_seconds=0)

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
        item = connection.execute("SELECT * FROM watch_items WHERE path = ?", (str(audio_path),)).fetchone()

    assert result.processed == 0
    assert result.skipped == 1
    assert item["status"] == "pending"


def test_scan_processes_future_mtime_file_after_unchanged_scan(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    audio_path = inbox / "future.mp3"
    audio_path.write_bytes(b"audio")
    future_timestamp = time.time() + 3600
    os.utime(audio_path, (future_timestamp, future_timestamp))
    calls = []

    def fake_process(connection, path, title, config, storage=None, progress=None):
        calls.append(path)
        connection.execute(
            "INSERT INTO meetings(id, slug, title, language) VALUES (?, ?, ?, ?)",
            ("meeting-1", "future", "Future", "sv"),
        )
        return SimpleNamespace(meeting=SimpleNamespace(id="meeting-1"))

    with database(tmp_path / "fly.db") as connection:
        add_watch_folder(connection, inbox)
        first = scan_watch_folders(
            connection,
            AppConfig(),
            process_fn=fake_process,
            stable_age_seconds=5,
        )
        second = scan_watch_folders(
            connection,
            AppConfig(),
            process_fn=fake_process,
            stable_age_seconds=5,
        )

    assert first.skipped == 1
    assert first.processed == 0
    assert second.processed == 1
    assert calls == [audio_path]


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
        item = connection.execute("SELECT * FROM watch_items WHERE path = ?", (str(audio_path),)).fetchone()

    assert result.failed == 1
    assert item["status"] == "failed"
    assert item["error_message"] == "provider unavailable"
    assert audio_path.exists()
