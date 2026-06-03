from pathlib import Path

from fly_on_the_wall.db import bootstrap_database, database
from fly_on_the_wall.service_pricing import get_service_price, list_service_prices


def test_database_seeds_default_service_prices(tmp_path: Path) -> None:
    database_path = tmp_path / "fly.db"

    bootstrap_database(database_path)

    with database(database_path) as connection:
        prices = list_service_prices(connection)
        openai = get_service_price(connection, "openai", "gpt-5.4-mini", "chat", "token")
        elevenlabs = get_service_price(
            connection,
            "elevenlabs",
            "scribe_v2",
            "transcription",
            "audio_second",
        )

    assert {price.id for price in prices} >= {
        "openai:gpt-5.4-mini:chat:token",
        "openai:gpt-5.4-nano:chat:token",
        "elevenlabs:scribe_v1:transcription:audio_second",
        "elevenlabs:scribe_v2:transcription:audio_second",
    }
    assert openai is not None
    assert openai.input_unit_price_usd == 0.00000075
    assert openai.output_unit_price_usd == 0.0000045
    assert openai.pricing["input_1m_tokens_usd"] == 0.75
    assert elevenlabs is not None
    assert elevenlabs.input_unit_price_usd == 0.0000611
    assert elevenlabs.pricing["litellm_fallback_key"] == "elevenlabs/scribe_v1"


def test_service_price_seed_is_idempotent(tmp_path: Path) -> None:
    database_path = tmp_path / "fly.db"

    bootstrap_database(database_path)
    bootstrap_database(database_path)

    with database(database_path) as connection:
        count = connection.execute("SELECT COUNT(*) FROM service_prices").fetchone()[0]

    assert count == 4
