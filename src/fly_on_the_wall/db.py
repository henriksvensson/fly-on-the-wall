from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from fly_on_the_wall.storage import ensure_storage_layout, storage_paths

SCHEMA_VERSION = 2

SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS schema_migrations (
        version INTEGER PRIMARY KEY,
        applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS meetings (
        id TEXT PRIMARY KEY,
        slug TEXT NOT NULL UNIQUE,
        title TEXT NOT NULL,
        description TEXT,
        language TEXT NOT NULL,
        original_audio_path TEXT,
        imported_audio_path TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS people (
        id TEXT PRIMARY KEY,
        display_name TEXT NOT NULL UNIQUE,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS pipeline_stages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        meeting_id TEXT NOT NULL,
        stage_name TEXT NOT NULL,
        status TEXT NOT NULL,
        error_message TEXT,
        started_at TEXT,
        completed_at TEXT,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(meeting_id, stage_name),
        FOREIGN KEY(meeting_id) REFERENCES meetings(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS provider_runs (
        id TEXT PRIMARY KEY,
        meeting_id TEXT NOT NULL,
        provider TEXT NOT NULL,
        model TEXT NOT NULL,
        settings_json TEXT NOT NULL DEFAULT '{}',
        raw_response_path TEXT,
        status TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        completed_at TEXT,
        FOREIGN KEY(meeting_id) REFERENCES meetings(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS local_speakers (
        id TEXT PRIMARY KEY,
        meeting_id TEXT NOT NULL,
        provider_run_id TEXT NOT NULL,
        label TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(provider_run_id, label),
        FOREIGN KEY(meeting_id) REFERENCES meetings(id) ON DELETE CASCADE,
        FOREIGN KEY(provider_run_id) REFERENCES provider_runs(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS segments (
        id TEXT PRIMARY KEY,
        meeting_id TEXT NOT NULL,
        provider_run_id TEXT NOT NULL,
        local_speaker_id TEXT,
        sequence INTEGER NOT NULL,
        start_time REAL,
        end_time REAL,
        text TEXT NOT NULL,
        language TEXT,
        source_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(provider_run_id, sequence),
        FOREIGN KEY(meeting_id) REFERENCES meetings(id) ON DELETE CASCADE,
        FOREIGN KEY(provider_run_id) REFERENCES provider_runs(id) ON DELETE CASCADE,
        FOREIGN KEY(local_speaker_id) REFERENCES local_speakers(id) ON DELETE SET NULL
    )
    """,
)


def connect(database_path: Path | None = None) -> sqlite3.Connection:
    if database_path is None:
        database_path = storage_paths().database
        ensure_storage_layout()

    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize_database(connection: sqlite3.Connection) -> None:
    with connection:
        for statement in SCHEMA_STATEMENTS:
            connection.execute(statement)
        connection.execute(
            "INSERT OR IGNORE INTO schema_migrations(version) VALUES (?)",
            (SCHEMA_VERSION,),
        )


def bootstrap_database(database_path: Path | None = None) -> Path:
    path = database_path or storage_paths().database
    with connect(path) as connection:
        initialize_database(connection)
    return path


@contextmanager
def database(database_path: Path | None = None) -> Iterator[sqlite3.Connection]:
    connection = connect(database_path)
    try:
        initialize_database(connection)
        yield connection
    finally:
        connection.close()
