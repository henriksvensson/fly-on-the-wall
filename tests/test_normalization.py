import json
from pathlib import Path

from fly_on_the_wall.db import database
from fly_on_the_wall.normalization import normalize_elevenlabs_response, normalize_provider_run


def test_normalize_elevenlabs_response_groups_consecutive_speakers() -> None:
    response = {
        "language_code": "sv",
        "words": [
            {"type": "word", "speaker_id": "speaker_0", "text": "Hej", "start": 0, "end": 0.2},
            {"type": "word", "speaker_id": "speaker_0", "text": " där", "start": 0.2, "end": 0.5},
            {"type": "word", "speaker_id": "speaker_1", "text": "Hallå", "start": 1, "end": 1.3},
        ],
    }

    segments = normalize_elevenlabs_response(response)

    assert [segment.speaker_label for segment in segments] == ["speaker_0", "speaker_1"]
    assert [segment.text for segment in segments] == ["Hej där", "Hallå"]
    assert segments[0].start_time == 0.0
    assert segments[0].end_time == 0.5
    assert segments[0].language == "sv"


def test_normalize_provider_run_stores_segments_and_local_speakers(tmp_path: Path) -> None:
    raw_response_path = tmp_path / "raw.json"
    raw_response_path.write_text(
        json.dumps(
            {
                "language_code": "sv",
                "words": [
                    {"speaker_id": "speaker_0", "text": "Hej", "start": 0, "end": 0.2},
                    {"speaker_id": "speaker_1", "text": "Hallå", "start": 1, "end": 1.3},
                ],
            }
        )
    )

    with database(tmp_path / "fly.db") as connection:
        connection.execute(
            "INSERT INTO meetings(id, slug, title, language) VALUES (?, ?, ?, ?)",
            ("meeting-1", "meeting-1", "Meeting", "sv"),
        )
        connection.execute(
            """
            INSERT INTO provider_runs(id, meeting_id, provider, model, raw_response_path, status)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("run-1", "meeting-1", "elevenlabs", "scribe_v2", str(raw_response_path), "done"),
        )

        segments = normalize_provider_run(connection, "run-1")
        stored_segments = connection.execute("SELECT * FROM segments ORDER BY sequence").fetchall()
        speakers = connection.execute("SELECT label FROM local_speakers ORDER BY label").fetchall()

    assert len(segments) == 2
    assert [row["text"] for row in stored_segments] == ["Hej", "Hallå"]
    assert [row["label"] for row in speakers] == ["speaker_0", "speaker_1"]
