from __future__ import annotations

from collections.abc import Callable
from sqlite3 import Connection

from fly_on_the_wall.meetings import get_meeting
from fly_on_the_wall.pipeline import STALE, set_stage_status
from fly_on_the_wall.speaker_identity import match_provider_run_speakers

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


def list_stale_meetings(connection: Connection) -> list[dict]:
    stages = list_stale_stages(connection)
    seen: set[str] = set()
    meetings: list[dict] = []
    for stage in stages:
        if stage["meeting_id"] in seen:
            continue
        seen.add(stage["meeting_id"])
        meetings.append(
            {
                "meeting_id": stage["meeting_id"],
                "meeting_slug": stage["meeting_slug"],
            }
        )
    return meetings


ProgressCallback = Callable[[str], None]


def rerun_speaker_matching(
    connection: Connection,
    meeting_id_or_slug: str,
    progress: ProgressCallback | None = None,
) -> int:
    meeting = get_meeting(connection, meeting_id_or_slug)
    if meeting is None:
        raise ValueError(f"Meeting not found: {meeting_id_or_slug}")

    provider_run = connection.execute(
        """
        SELECT id FROM provider_runs
        WHERE meeting_id = ? AND status = 'done'
        ORDER BY completed_at DESC, created_at DESC
        LIMIT 1
        """,
        (meeting["id"],),
    ).fetchone()
    if provider_run is None:
        raise ValueError(f"No completed provider run found for meeting: {meeting_id_or_slug}")

    if progress is not None:
        progress(f"Embedding and matching speakers for {meeting['slug']}")
    before = _speaker_assignment_snapshot(connection, provider_run["id"])
    match_provider_run_speakers(connection, provider_run["id"])
    after = _speaker_assignment_snapshot(connection, provider_run["id"])
    return _changed_assignment_count(before, after)


def rerun_speaker_matching_for_meetings(
    connection: Connection,
    include_known_speakers: bool = False,
    progress: ProgressCallback | None = None,
) -> list[dict]:
    results: list[dict] = []
    meetings = _speaker_reanalysis_meetings(connection, include_known_speakers)
    if progress is not None:
        progress(f"Found {len(meetings)} meeting(s) for speaker refresh")
    for index, meeting in enumerate(meetings, start=1):
        if progress is not None:
            progress(f"Refreshing speaker matching for {meeting['slug']} ({index}/{len(meetings)})")
        changed_count = rerun_speaker_matching(connection, meeting["id"], progress)
        stages = mark_speaker_reanalysis_stale(connection, meeting["id"]) if changed_count else []
        if progress is not None:
            progress(f"{meeting['slug']}: {changed_count} speaker assignment change(s)")
        results.append(
            {
                "meeting_id": meeting["id"],
                "meeting_slug": meeting["slug"],
                "match_count": changed_count,
                "marked_stale": stages,
            }
        )
    return results


def _speaker_reanalysis_meetings(connection: Connection, include_known_speakers: bool) -> list[dict]:
    if include_known_speakers:
        rows = connection.execute(
            """
            SELECT DISTINCT meetings.id, meetings.slug
            FROM meetings
            JOIN provider_runs ON provider_runs.meeting_id = meetings.id
            WHERE provider_runs.status = 'done'
            ORDER BY meetings.created_at DESC
            """
        ).fetchall()
    else:
        rows = connection.execute(
            """
            SELECT DISTINCT meetings.id, meetings.slug
            FROM meetings
            JOIN provider_runs ON provider_runs.meeting_id = meetings.id
            JOIN local_speakers ON local_speakers.meeting_id = meetings.id
            LEFT JOIN speaker_assignments
                ON speaker_assignments.local_speaker_id = local_speakers.id
            WHERE provider_runs.status = 'done'
              AND (speaker_assignments.id IS NULL OR speaker_assignments.status = 'unknown')
            ORDER BY meetings.created_at DESC
            """
        ).fetchall()
    return [dict(row) for row in rows]


def _speaker_assignment_snapshot(connection: Connection, provider_run_id: str) -> dict[str, tuple]:
    rows = connection.execute(
        """
        SELECT local_speakers.id AS local_speaker_id,
               speaker_assignments.person_id,
               speaker_assignments.status,
               speaker_assignments.confidence,
               speaker_assignments.margin,
               speaker_assignments.evidence_json
        FROM local_speakers
        LEFT JOIN speaker_assignments
            ON speaker_assignments.local_speaker_id = local_speakers.id
        WHERE local_speakers.provider_run_id = ?
        ORDER BY local_speakers.id
        """,
        (provider_run_id,),
    ).fetchall()
    return {
        row["local_speaker_id"]: (
            row["person_id"],
            row["status"],
            row["confidence"],
            row["margin"],
            row["evidence_json"],
        )
        for row in rows
    }


def _changed_assignment_count(before: dict[str, tuple], after: dict[str, tuple]) -> int:
    return sum(1 for speaker_id, assignment in after.items() if before.get(speaker_id) != assignment)
