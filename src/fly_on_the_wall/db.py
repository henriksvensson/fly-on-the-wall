from __future__ import annotations

import json
import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from fly_on_the_wall.storage import ensure_storage_layout, storage_paths

SCHEMA_VERSION = 17

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
        title_source TEXT NOT NULL DEFAULT 'manual',
        generated_title TEXT,
        description TEXT,
        language TEXT NOT NULL,
        original_audio_path TEXT,
        imported_audio_path TEXT,
        audio_sha256 TEXT UNIQUE,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS people (
        id TEXT PRIMARY KEY,
        display_name TEXT NOT NULL UNIQUE,
        is_user INTEGER NOT NULL DEFAULT 0,
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
    """
    CREATE TABLE IF NOT EXISTS voice_samples (
        id TEXT PRIMARY KEY,
        person_id TEXT NOT NULL,
        source_meeting_id TEXT,
        source_local_speaker_id TEXT,
        start_time REAL,
        end_time REAL,
        audio_path TEXT NOT NULL,
        embedding_model TEXT,
        embedding_path TEXT,
        quality_score REAL,
        confirmed_by_user INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(person_id) REFERENCES people(id) ON DELETE CASCADE,
        FOREIGN KEY(source_meeting_id) REFERENCES meetings(id) ON DELETE SET NULL,
        FOREIGN KEY(source_local_speaker_id) REFERENCES local_speakers(id) ON DELETE SET NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS local_speaker_embeddings (
        id TEXT PRIMARY KEY,
        local_speaker_id TEXT NOT NULL,
        audio_path TEXT NOT NULL,
        embedding_model TEXT NOT NULL,
        embedding_path TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(local_speaker_id, embedding_model),
        FOREIGN KEY(local_speaker_id) REFERENCES local_speakers(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS speaker_assignments (
        id TEXT PRIMARY KEY,
        local_speaker_id TEXT NOT NULL,
        person_id TEXT,
        status TEXT NOT NULL,
        confidence REAL,
        margin REAL,
        evidence_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(local_speaker_id),
        FOREIGN KEY(local_speaker_id) REFERENCES local_speakers(id) ON DELETE CASCADE,
        FOREIGN KEY(person_id) REFERENCES people(id) ON DELETE SET NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS exports (
        id TEXT PRIMARY KEY,
        meeting_id TEXT NOT NULL,
        format TEXT NOT NULL,
        output_dir TEXT NOT NULL,
        manifest_path TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(meeting_id) REFERENCES meetings(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS corrections (
        id TEXT PRIMARY KEY,
        correction_type TEXT NOT NULL,
        meeting_id TEXT,
        local_speaker_id TEXT,
        person_id TEXT,
        details_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(meeting_id) REFERENCES meetings(id) ON DELETE SET NULL,
        FOREIGN KEY(local_speaker_id) REFERENCES local_speakers(id) ON DELETE SET NULL,
        FOREIGN KEY(person_id) REFERENCES people(id) ON DELETE SET NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS audio_metadata (
        id TEXT PRIMARY KEY,
        meeting_id TEXT NOT NULL UNIQUE,
        raw_metadata_path TEXT,
        recorded_at TEXT,
        recorded_at_source TEXT,
        recorded_at_confidence TEXT,
        duration_seconds REAL,
        size_bytes INTEGER,
        bit_rate INTEGER,
        codec TEXT,
        sample_rate INTEGER,
        channels INTEGER,
        channel_layout TEXT,
        container_format TEXT,
        metadata_title TEXT,
        metadata_artist TEXT,
        metadata_album TEXT,
        metadata_genre TEXT,
        metadata_comment TEXT,
        metadata_encoder TEXT,
        device_or_software TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(meeting_id) REFERENCES meetings(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS recording_quality (
        id TEXT PRIMARY KEY,
        meeting_id TEXT NOT NULL UNIQUE,
        status TEXT NOT NULL,
        reason TEXT NOT NULL,
        details_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(meeting_id) REFERENCES meetings(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS watch_folders (
        id TEXT PRIMARY KEY,
        name TEXT UNIQUE,
        path TEXT NOT NULL UNIQUE,
        enabled INTEGER NOT NULL DEFAULT 1,
        delete_originals_after_import INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS watch_items (
        id TEXT PRIMARY KEY,
        folder_id TEXT NOT NULL,
        path TEXT NOT NULL UNIQUE,
        file_sha256 TEXT,
        size_bytes INTEGER,
        mtime_ns INTEGER,
        status TEXT NOT NULL,
        meeting_id TEXT,
        error_message TEXT,
        first_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        processed_at TEXT,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(folder_id) REFERENCES watch_folders(id) ON DELETE CASCADE,
        FOREIGN KEY(meeting_id) REFERENCES meetings(id) ON DELETE SET NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS publish_targets (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL UNIQUE,
        target_type TEXT NOT NULL,
        path TEXT NOT NULL,
        settings_json TEXT NOT NULL DEFAULT '{}',
        auto_publish INTEGER NOT NULL DEFAULT 0,
        enabled INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS published_items (
        id TEXT PRIMARY KEY,
        meeting_id TEXT NOT NULL,
        target_id TEXT NOT NULL,
        output_path TEXT NOT NULL,
        content_sha256 TEXT NOT NULL,
        published_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(meeting_id, target_id),
        FOREIGN KEY(meeting_id) REFERENCES meetings(id) ON DELETE CASCADE,
        FOREIGN KEY(target_id) REFERENCES publish_targets(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS service_prices (
        id TEXT PRIMARY KEY,
        provider TEXT NOT NULL,
        model TEXT NOT NULL,
        service TEXT NOT NULL,
        unit TEXT NOT NULL,
        input_unit_price_usd REAL,
        output_unit_price_usd REAL,
        cached_input_unit_price_usd REAL,
        currency TEXT NOT NULL DEFAULT 'USD',
        source_name TEXT NOT NULL,
        source_url TEXT,
        pricing_json TEXT NOT NULL DEFAULT '{}',
        active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(provider, model, service, unit, source_name)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS service_usage (
        id TEXT PRIMARY KEY,
        meeting_id TEXT,
        provider_run_id TEXT,
        provider TEXT NOT NULL,
        model TEXT NOT NULL,
        service TEXT NOT NULL,
        unit TEXT NOT NULL,
        input_quantity REAL NOT NULL DEFAULT 0,
        output_quantity REAL NOT NULL DEFAULT 0,
        cache_hit INTEGER NOT NULL DEFAULT 0,
        billable INTEGER NOT NULL DEFAULT 1,
        input_unit_price_usd REAL,
        output_unit_price_usd REAL,
        estimated_cost_usd REAL,
        currency TEXT NOT NULL DEFAULT 'USD',
        usage_json TEXT NOT NULL DEFAULT '{}',
        pricing_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(meeting_id) REFERENCES meetings(id) ON DELETE CASCADE,
        FOREIGN KEY(provider_run_id) REFERENCES provider_runs(id) ON DELETE SET NULL
    )
    """,
)


DEFAULT_SERVICE_PRICES = (
    {
        "id": "openai:gpt-5.4-mini:chat:token",
        "provider": "openai",
        "model": "gpt-5.4-mini",
        "service": "chat",
        "unit": "token",
        "input_unit_price_usd": 0.00000075,
        "output_unit_price_usd": 0.0000045,
        "cached_input_unit_price_usd": 0.000000075,
        "source_name": "openai-pricing",
        "source_url": "https://openai.com/api/pricing/",
        "pricing_json": {
            "input_1m_tokens_usd": 0.75,
            "output_1m_tokens_usd": 4.50,
            "cached_input_1m_tokens_usd": 0.075,
            "litellm_key": "gpt-5.4-mini",
            "litellm_price_fields": {
                "input_cost_per_token": 0.00000075,
                "output_cost_per_token": 0.0000045,
                "cache_read_input_token_cost": 0.000000075,
            },
        },
    },
    {
        "id": "openai:gpt-5.4-nano:chat:token",
        "provider": "openai",
        "model": "gpt-5.4-nano",
        "service": "chat",
        "unit": "token",
        "input_unit_price_usd": 0.0000002,
        "output_unit_price_usd": 0.00000125,
        "cached_input_unit_price_usd": 0.00000002,
        "source_name": "openai-pricing",
        "source_url": "https://openai.com/api/pricing/",
        "pricing_json": {
            "input_1m_tokens_usd": 0.20,
            "output_1m_tokens_usd": 1.25,
            "cached_input_1m_tokens_usd": 0.02,
            "litellm_key": "gpt-5.4-nano",
            "litellm_price_fields": {
                "input_cost_per_token": 0.0000002,
                "output_cost_per_token": 0.00000125,
                "cache_read_input_token_cost": 0.00000002,
            },
        },
    },
    {
        "id": "elevenlabs:scribe_v1:transcription:audio_second",
        "provider": "elevenlabs",
        "model": "scribe_v1",
        "service": "transcription",
        "unit": "audio_second",
        "input_unit_price_usd": 0.0000611,
        "output_unit_price_usd": 0.0,
        "cached_input_unit_price_usd": None,
        "source_name": "elevenlabs-pricing",
        "source_url": "https://elevenlabs.io/pricing",
        "pricing_json": {
            "input_audio_hour_usd": 0.22,
            "input_audio_second_usd": 0.0000611,
            "litellm_key": "elevenlabs/scribe_v1",
            "litellm_price_fields": {"input_cost_per_second": 0.0000611},
            "note": "LiteLLM describes this as enterprise pricing from ElevenLabs pricing.",
        },
    },
    {
        "id": "elevenlabs:scribe_v2:transcription:audio_second",
        "provider": "elevenlabs",
        "model": "scribe_v2",
        "service": "transcription",
        "unit": "audio_second",
        "input_unit_price_usd": 0.0000611,
        "output_unit_price_usd": 0.0,
        "cached_input_unit_price_usd": None,
        "source_name": "elevenlabs-pricing",
        "source_url": "https://elevenlabs.io/pricing",
        "pricing_json": {
            "input_audio_hour_usd": 0.22,
            "input_audio_second_usd": 0.0000611,
            "litellm_fallback_key": "elevenlabs/scribe_v1",
            "inferred_for_model": "scribe_v2",
            "litellm_price_fields": {"input_cost_per_second": 0.0000611},
            "note": ("Exact scribe_v2 entry was not present in LiteLLM; seeded from Scribe pricing fallback."),
        },
    },
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
        _ensure_column(connection, "meetings", "audio_sha256", "TEXT")
        _ensure_column(connection, "meetings", "title_source", "TEXT NOT NULL DEFAULT 'manual'")
        _ensure_column(connection, "meetings", "generated_title", "TEXT")
        _ensure_column(connection, "people", "is_user", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(
            connection,
            "watch_folders",
            "delete_originals_after_import",
            "INTEGER NOT NULL DEFAULT 0",
        )
        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_meetings_audio_sha256
            ON meetings(audio_sha256)
            WHERE audio_sha256 IS NOT NULL
            """
        )
        connection.execute(
            "INSERT OR IGNORE INTO schema_migrations(version) VALUES (?)",
            (SCHEMA_VERSION,),
        )
        _seed_default_service_prices(connection)


def _ensure_column(connection: sqlite3.Connection, table_name: str, column_name: str, definition: str) -> None:
    columns = {row["name"] for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()}
    if column_name not in columns:
        connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")


def _seed_default_service_prices(connection: sqlite3.Connection) -> None:
    for price in DEFAULT_SERVICE_PRICES:
        connection.execute(
            """
            INSERT INTO service_prices(
                id,
                provider,
                model,
                service,
                unit,
                input_unit_price_usd,
                output_unit_price_usd,
                cached_input_unit_price_usd,
                currency,
                source_name,
                source_url,
                pricing_json,
                active
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(provider, model, service, unit, source_name) DO UPDATE SET
                input_unit_price_usd = excluded.input_unit_price_usd,
                output_unit_price_usd = excluded.output_unit_price_usd,
                cached_input_unit_price_usd = excluded.cached_input_unit_price_usd,
                currency = excluded.currency,
                source_url = excluded.source_url,
                pricing_json = excluded.pricing_json,
                active = excluded.active,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                price["id"],
                price["provider"],
                price["model"],
                price["service"],
                price["unit"],
                price["input_unit_price_usd"],
                price["output_unit_price_usd"],
                price["cached_input_unit_price_usd"],
                "USD",
                price["source_name"],
                price["source_url"],
                json.dumps(price["pricing_json"], sort_keys=True),
                1,
            ),
        )


def bootstrap_database(database_path: Path | None = None) -> Path:
    path = database_path or storage_paths().database
    with connect(path) as connection:
        initialize_database(connection)
    return path


@contextmanager
def database(database_path: Path | None = None) -> Generator[sqlite3.Connection]:
    connection = connect(database_path)
    try:
        initialize_database(connection)
        yield connection
    finally:
        connection.close()
