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


def _format_turn(speaker_label: str, language: str | None, text: str) -> str:
    language_marker = f" [{language}]" if language else ""
    return f"{speaker_label}{language_marker}: {text}"
