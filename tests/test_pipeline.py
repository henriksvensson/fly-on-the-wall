from sqlite3 import Connection

import pytest

from fly_on_the_wall.db import database
from fly_on_the_wall.pipeline import (
    DONE,
    FAILED,
    STALE,
    PipelineError,
    Stage,
    get_stage_status,
    mark_stale,
    run_pipeline,
)


def insert_meeting(connection: Connection, meeting_id: str = "meeting-1") -> None:
    connection.execute(
        """
        INSERT INTO meetings(id, slug, title, language)
        VALUES (?, ?, ?, ?)
        """,
        (meeting_id, meeting_id, "Meeting", "sv"),
    )


def test_run_pipeline_records_done_stages(tmp_path) -> None:
    calls: list[str] = []

    def run(connection: Connection, meeting_id: str) -> None:
        calls.append(meeting_id)

    with database(tmp_path / "fly.db") as connection:
        insert_meeting(connection)
        completed = run_pipeline(connection, "meeting-1", [Stage("import", run)])

        assert completed == ["import"]
        assert calls == ["meeting-1"]
        assert get_stage_status(connection, "meeting-1", "import") == DONE


def test_run_pipeline_skips_done_stage_unless_forced(tmp_path) -> None:
    calls = 0

    def run(connection: Connection, meeting_id: str) -> None:
        nonlocal calls
        calls += 1

    with database(tmp_path / "fly.db") as connection:
        insert_meeting(connection)
        stage = Stage("import", run)
        run_pipeline(connection, "meeting-1", [stage])
        run_pipeline(connection, "meeting-1", [stage])
        run_pipeline(connection, "meeting-1", [stage], force=True)

    assert calls == 2


def test_run_pipeline_records_failed_stage(tmp_path) -> None:
    def fail(connection: Connection, meeting_id: str) -> None:
        raise RuntimeError("boom")

    with database(tmp_path / "fly.db") as connection:
        insert_meeting(connection)
        with pytest.raises(RuntimeError, match="boom"):
            run_pipeline(connection, "meeting-1", [Stage("import", fail)])

        assert get_stage_status(connection, "meeting-1", "import") == FAILED


def test_run_pipeline_requires_dependencies(tmp_path) -> None:
    def run(connection: Connection, meeting_id: str) -> None:
        pass

    with database(tmp_path / "fly.db") as connection:
        insert_meeting(connection)
        with pytest.raises(PipelineError, match="Unknown dependency"):
            run_pipeline(connection, "meeting-1", [Stage("render", run, ("transcribe",))])


def test_mark_stale_updates_stage_status(tmp_path) -> None:
    def run(connection: Connection, meeting_id: str) -> None:
        pass

    with database(tmp_path / "fly.db") as connection:
        insert_meeting(connection)
        run_pipeline(connection, "meeting-1", [Stage("render", run)])
        mark_stale(connection, "meeting-1", ["render"])

        assert get_stage_status(connection, "meeting-1", "render") == STALE
