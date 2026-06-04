from pathlib import Path

from fly_on_the_wall.db import database
from fly_on_the_wall.normalization import normalize_provider_run
from fly_on_the_wall.rendering import render_named_transcript

FIXTURES = Path(__file__).parent / "fixtures"


def test_golden_provider_json_to_named_transcript(tmp_path: Path) -> None:
    raw_path = FIXTURES / "elevenlabs_raw.json"

    with database(tmp_path / "fly.db") as connection:
        connection.execute(
            "INSERT INTO meetings(id, slug, title, language) VALUES (?, ?, ?, ?)",
            ("meeting-1", "intro", "Intro", "sv"),
        )
        connection.execute(
            """
            INSERT INTO provider_runs(id, meeting_id, provider, model, raw_response_path, status)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("run-1", "meeting-1", "elevenlabs", "scribe_v2", str(raw_path), "done"),
        )
        connection.execute("INSERT INTO people(id, display_name) VALUES (?, ?)", ("person-1", "Person B"))
        normalize_provider_run(connection, "run-1")
        speaker_id = connection.execute("SELECT id FROM local_speakers WHERE label = ?", ("speaker_0",)).fetchone()[
            "id"
        ]
        connection.execute(
            """
            INSERT INTO speaker_assignments(id, local_speaker_id, person_id, status)
            VALUES (?, ?, ?, ?)
            """,
            ("assignment-1", speaker_id, "person-1", "known"),
        )
        transcript = render_named_transcript(connection, "run-1")

    assert transcript == (FIXTURES / "named_transcript.txt").read_text().strip()
