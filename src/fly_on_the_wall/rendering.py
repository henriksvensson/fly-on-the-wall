from __future__ import annotations

from pathlib import Path
from sqlite3 import Connection

from fly_on_the_wall.storage import StoragePaths, storage_paths


def render_diarized_transcript(
    connection: Connection,
    provider_run_id: str,
    output_path: Path | None = None,
    storage: StoragePaths | None = None,
) -> str:
    rows = connection.execute(
        """
        SELECT segments.text,
               segments.language,
               local_speakers.label AS speaker_label
        FROM segments
        LEFT JOIN local_speakers ON local_speakers.id = segments.local_speaker_id
        WHERE segments.provider_run_id = ?
        ORDER BY segments.sequence
        """,
        (provider_run_id,),
    ).fetchall()
    transcript = "\n\n".join(
        _format_turn(row["speaker_label"] or "Unknown", row["language"], row["text"])
        for row in rows
    )

    if output_path is None:
        provider_run = connection.execute(
            "SELECT meeting_id FROM provider_runs WHERE id = ?", (provider_run_id,)
        ).fetchone()
        if provider_run is not None:
            paths = storage or storage_paths()
            output_path = paths.artifacts / provider_run["meeting_id"] / "diarized-transcript.txt"

    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(transcript + "\n")

    return transcript


def render_named_transcript(
    connection: Connection,
    provider_run_id: str,
    output_path: Path | None = None,
    storage: StoragePaths | None = None,
) -> str:
    rows = connection.execute(
        """
        SELECT segments.text,
               segments.language,
               local_speakers.label AS speaker_label,
               speaker_assignments.status AS assignment_status,
               people.display_name
        FROM segments
        LEFT JOIN local_speakers ON local_speakers.id = segments.local_speaker_id
        LEFT JOIN speaker_assignments
            ON speaker_assignments.local_speaker_id = local_speakers.id
        LEFT JOIN people ON people.id = speaker_assignments.person_id
        WHERE segments.provider_run_id = ?
        ORDER BY segments.sequence
        """,
        (provider_run_id,),
    ).fetchall()
    transcript = "\n\n".join(
        _format_named_turn(
            row["display_name"],
            row["assignment_status"],
            row["speaker_label"] or "Unknown",
            row["language"],
            row["text"],
        )
        for row in rows
    )

    if output_path is None:
        provider_run = connection.execute(
            "SELECT meeting_id FROM provider_runs WHERE id = ?", (provider_run_id,)
        ).fetchone()
        if provider_run is not None:
            paths = storage or storage_paths()
            output_path = paths.artifacts / provider_run["meeting_id"] / "named-transcript.txt"

    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(transcript + "\n")

    return transcript


def _format_turn(speaker_label: str, language: str | None, text: str) -> str:
    language_marker = f" [{language}]" if language else ""
    return f"{speaker_label}{language_marker}: {text}"


def _format_named_turn(
    display_name: str | None,
    assignment_status: str | None,
    speaker_label: str,
    language: str | None,
    text: str,
) -> str:
    if assignment_status == "known" and display_name:
        name = display_name
    elif assignment_status == "uncertain" and display_name:
        name = f"{display_name}?"
    else:
        name = "Unknown"

    language_marker = f" [{language}]" if language else ""
    return f"{name}{language_marker} ({speaker_label}): {text}"
