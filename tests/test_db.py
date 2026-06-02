from pathlib import Path

from fly_on_the_wall.db import SCHEMA_VERSION, bootstrap_database, database


def test_bootstrap_database_creates_file_and_schema(tmp_path: Path) -> None:
    database_path = tmp_path / "fly.db"

    bootstrap_database(database_path)

    assert database_path.exists()

    with database(database_path) as connection:
        tables = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }

    assert "schema_migrations" in tables
    assert "meetings" in tables
    assert "people" in tables
    assert "pipeline_stages" in tables
    assert "provider_runs" in tables


def test_bootstrap_database_records_schema_version(tmp_path: Path) -> None:
    database_path = tmp_path / "fly.db"

    bootstrap_database(database_path)

    with database(database_path) as connection:
        row = connection.execute("SELECT version FROM schema_migrations").fetchone()

    assert row["version"] == SCHEMA_VERSION


def test_bootstrap_database_adds_audio_hash_column(tmp_path: Path) -> None:
    database_path = tmp_path / "fly.db"

    bootstrap_database(database_path)

    with database(database_path) as connection:
        columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(meetings)").fetchall()
        }

    assert "audio_sha256" in columns


def test_database_context_enables_foreign_keys(tmp_path: Path) -> None:
    with database(tmp_path / "fly.db") as connection:
        row = connection.execute("PRAGMA foreign_keys").fetchone()

    assert row[0] == 1
