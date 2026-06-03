import pytest

from fly_on_the_wall.costs import cost_summary, meeting_cost_summary, record_service_usage
from fly_on_the_wall.db import database


def test_record_service_usage_estimates_cost_from_seeded_price(tmp_path) -> None:
    with database(tmp_path / "fly.db") as connection:
        connection.execute(
            "INSERT INTO meetings(id, slug, title, language) VALUES (?, ?, ?, ?)",
            ("meeting-1", "intro", "Intro", "sv"),
        )

        record = record_service_usage(
            connection,
            meeting_id="meeting-1",
            provider="openai",
            model="gpt-5.4-mini",
            service="cleanup",
            unit="token",
            input_quantity=1000,
            output_quantity=100,
            usage={"prompt_tokens": 1000, "completion_tokens": 100},
        )
        rows = meeting_cost_summary(connection, "intro")

    assert record.estimated_cost_usd == pytest.approx(0.0012)
    assert rows[0]["estimated_cost_usd"] == pytest.approx(0.0012)


def test_cost_summary_groups_by_provider_and_service(tmp_path) -> None:
    with database(tmp_path / "fly.db") as connection:
        record_service_usage(
            connection,
            provider="elevenlabs",
            model="scribe_v2",
            service="transcription",
            unit="audio_second",
            input_quantity=10,
        )

        rows = cost_summary(connection)

    assert rows == [
        {
            "provider": "elevenlabs",
            "service": "transcription",
            "calls": 1,
            "input_quantity": 10.0,
            "output_quantity": 0.0,
            "estimated_cost_usd": 0.000611,
        }
    ]
