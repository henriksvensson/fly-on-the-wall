from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from sqlite3 import Connection

StageStatus = str

PENDING: StageStatus = "pending"
RUNNING: StageStatus = "running"
DONE: StageStatus = "done"
FAILED: StageStatus = "failed"
STALE: StageStatus = "stale"


class PipelineError(RuntimeError):
    """Raised when a pipeline stage cannot run."""


@dataclass(frozen=True)
class Stage:
    name: str
    run: Callable[[Connection, str], None]
    dependencies: tuple[str, ...] = field(default_factory=tuple)


def run_pipeline(
    connection: Connection,
    meeting_id: str,
    stages: Sequence[Stage],
    force: bool = False,
) -> list[str]:
    completed: list[str] = []
    stage_by_name = {stage.name: stage for stage in stages}

    for stage in stages:
        _ensure_dependencies_done(connection, meeting_id, stage, stage_by_name)
        if not force and get_stage_status(connection, meeting_id, stage.name) == DONE:
            continue
        run_stage(connection, meeting_id, stage)
        completed.append(stage.name)

    return completed


def run_stage(connection: Connection, meeting_id: str, stage: Stage) -> None:
    set_stage_status(connection, meeting_id, stage.name, RUNNING)
    try:
        stage.run(connection, meeting_id)
    except Exception as exc:
        set_stage_status(connection, meeting_id, stage.name, FAILED, str(exc))
        raise
    set_stage_status(connection, meeting_id, stage.name, DONE)


def get_stage_status(
    connection: Connection, meeting_id: str, stage_name: str
) -> StageStatus | None:
    row = connection.execute(
        "SELECT status FROM pipeline_stages WHERE meeting_id = ? AND stage_name = ?",
        (meeting_id, stage_name),
    ).fetchone()
    return None if row is None else row["status"]


def set_stage_status(
    connection: Connection,
    meeting_id: str,
    stage_name: str,
    status: StageStatus,
    error_message: str | None = None,
) -> None:
    with connection:
        connection.execute(
            """
            INSERT INTO pipeline_stages(
                meeting_id,
                stage_name,
                status,
                error_message,
                started_at,
                completed_at,
                updated_at
            ) VALUES (
                ?,
                ?,
                ?,
                ?,
                CASE WHEN ? = 'running' THEN CURRENT_TIMESTAMP ELSE NULL END,
                CASE WHEN ? = 'done' THEN CURRENT_TIMESTAMP ELSE NULL END,
                CURRENT_TIMESTAMP
            )
            ON CONFLICT(meeting_id, stage_name) DO UPDATE SET
                status = excluded.status,
                error_message = excluded.error_message,
                started_at = CASE
                    WHEN excluded.status = 'running' THEN CURRENT_TIMESTAMP
                    ELSE pipeline_stages.started_at
                END,
                completed_at = CASE
                    WHEN excluded.status = 'done' THEN CURRENT_TIMESTAMP
                    ELSE NULL
                END,
                updated_at = CURRENT_TIMESTAMP
            """,
            (meeting_id, stage_name, status, error_message, status, status),
        )


def mark_stale(connection: Connection, meeting_id: str, stage_names: Sequence[str]) -> None:
    for stage_name in stage_names:
        set_stage_status(connection, meeting_id, stage_name, STALE)


def _ensure_dependencies_done(
    connection: Connection, meeting_id: str, stage: Stage, stage_by_name: dict[str, Stage]
) -> None:
    for dependency in stage.dependencies:
        if dependency not in stage_by_name:
            raise PipelineError(f"Unknown dependency {dependency!r} for stage {stage.name!r}.")
        if get_stage_status(connection, meeting_id, dependency) != DONE:
            raise PipelineError(f"Stage {stage.name!r} requires {dependency!r} to be done.")
