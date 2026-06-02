from __future__ import annotations

from sqlite3 import Connection

from fly_on_the_wall.meetings import get_meeting
from fly_on_the_wall.pipeline import STALE, set_stage_status

SPEAKER_DEPENDENT_STAGES = ("speaker_matching", "render", "cleanup", "export")


def mark_speaker_reanalysis_stale(connection: Connection, meeting_id_or_slug: str) -> list[str]:
    meeting = get_meeting(connection, meeting_id_or_slug)
    if meeting is None:
        raise ValueError(f"Meeting not found: {meeting_id_or_slug}")
    for stage in SPEAKER_DEPENDENT_STAGES:
        set_stage_status(connection, meeting["id"], stage, STALE)
    return list(SPEAKER_DEPENDENT_STAGES)


def list_stale_stages(connection: Connection) -> list[dict]:
    rows = connection.execute(
        """
        SELECT meetings.slug AS meeting_slug,
               pipeline_stages.meeting_id,
               pipeline_stages.stage_name,
               pipeline_stages.updated_at
        FROM pipeline_stages
        JOIN meetings ON meetings.id = pipeline_stages.meeting_id
        WHERE pipeline_stages.status = 'stale'
        ORDER BY pipeline_stages.updated_at DESC
        """
    ).fetchall()
    return [dict(row) for row in rows]
