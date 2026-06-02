from __future__ import annotations

from sqlite3 import Connection


def list_unknown_speakers(
    connection: Connection, meeting_id_or_slug: str | None = None
) -> list[dict]:
    params: list[str] = []
    meeting_filter = ""
    if meeting_id_or_slug:
        meeting_filter = "AND (meetings.id = ? OR meetings.slug = ?)"
        params.extend([meeting_id_or_slug, meeting_id_or_slug])

    rows = connection.execute(
        f"""
        SELECT local_speakers.id,
               local_speakers.label,
               meetings.slug AS meeting_slug,
               provider_runs.id AS provider_run_id,
               COUNT(segments.id) AS segment_count
        FROM local_speakers
        JOIN meetings ON meetings.id = local_speakers.meeting_id
        JOIN provider_runs ON provider_runs.id = local_speakers.provider_run_id
        LEFT JOIN segments ON segments.local_speaker_id = local_speakers.id
        LEFT JOIN speaker_assignments
            ON speaker_assignments.local_speaker_id = local_speakers.id
        WHERE (speaker_assignments.id IS NULL OR speaker_assignments.status = 'unknown')
        {meeting_filter}
        GROUP BY local_speakers.id
        ORDER BY meetings.created_at DESC, local_speakers.label
        """,
        params,
    ).fetchall()
    return [dict(row) for row in rows]
