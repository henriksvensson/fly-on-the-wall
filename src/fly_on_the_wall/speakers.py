from __future__ import annotations

import json
from sqlite3 import Connection
from uuid import uuid4

from fly_on_the_wall.people import create_person, get_person


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


def speaker_examples(connection: Connection, local_speaker_id: str, limit: int = 3) -> list[dict]:
    rows = connection.execute(
        """
        SELECT text, start_time, end_time
        FROM segments
        WHERE local_speaker_id = ?
        ORDER BY sequence
        LIMIT ?
        """,
        (local_speaker_id, limit),
    ).fetchall()
    return [dict(row) for row in rows]


def assign_speaker_to_person(
    connection: Connection, local_speaker_id: str, person_id_or_name: str
) -> dict:
    person = get_person(connection, person_id_or_name)
    if person is None:
        raise ValueError(f"Person not found: {person_id_or_name}")

    meeting_id = _local_speaker_meeting_id(connection, local_speaker_id)
    if meeting_id is None:
        raise ValueError(f"Local speaker not found: {local_speaker_id}")

    with connection:
        connection.execute(
            """
            INSERT INTO speaker_assignments(id, local_speaker_id, person_id, status, evidence_json)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(local_speaker_id) DO UPDATE SET
                person_id = excluded.person_id,
                status = excluded.status,
                evidence_json = excluded.evidence_json
            """,
            (
                str(uuid4()),
                local_speaker_id,
                person.id,
                "known",
                json.dumps({"method": "user_correction"}),
            ),
        )
        _record_correction(
            connection, "speaker_assignment", meeting_id, local_speaker_id, person.id
        )
    return {
        "local_speaker_id": local_speaker_id,
        "person_id": person.id,
        "name": person.display_name,
    }


def create_person_from_speaker(connection: Connection, local_speaker_id: str, name: str) -> dict:
    person = create_person(connection, name)
    return assign_speaker_to_person(connection, local_speaker_id, person.id)


def mark_speaker_unknown(connection: Connection, local_speaker_id: str) -> None:
    meeting_id = _local_speaker_meeting_id(connection, local_speaker_id)
    if meeting_id is None:
        raise ValueError(f"Local speaker not found: {local_speaker_id}")

    with connection:
        connection.execute(
            """
            INSERT INTO speaker_assignments(id, local_speaker_id, person_id, status, evidence_json)
            VALUES (?, ?, NULL, ?, ?)
            ON CONFLICT(local_speaker_id) DO UPDATE SET
                person_id = NULL,
                status = excluded.status,
                evidence_json = excluded.evidence_json
            """,
            (
                str(uuid4()),
                local_speaker_id,
                "unknown",
                json.dumps({"method": "user_correction"}),
            ),
        )
        _record_correction(connection, "speaker_assignment", meeting_id, local_speaker_id, None)


def _local_speaker_meeting_id(connection: Connection, local_speaker_id: str) -> str | None:
    row = connection.execute(
        "SELECT meeting_id FROM local_speakers WHERE id = ?", (local_speaker_id,)
    ).fetchone()
    return None if row is None else row["meeting_id"]


def _record_correction(
    connection: Connection,
    correction_type: str,
    meeting_id: str,
    local_speaker_id: str,
    person_id: str | None,
) -> None:
    connection.execute(
        """
        INSERT INTO corrections(id, correction_type, meeting_id, local_speaker_id, person_id)
        VALUES (?, ?, ?, ?, ?)
        """,
        (str(uuid4()), correction_type, meeting_id, local_speaker_id, person_id),
    )
