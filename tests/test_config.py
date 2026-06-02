from pathlib import Path

import pytest

from fly_on_the_wall.config import ConfigError, get_api_key, load_config


def test_load_config_uses_defaults_when_file_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config-home"))

    config = load_config()

    assert config.default_transcription_provider == "elevenlabs"
    assert config.language == "sv"
    assert config.cleanup_mode == "light"
    assert config.export_destination is None
    assert config.confidence_thresholds.named == 0.78
    assert config.glossary_path == tmp_path / "config-home" / "fly-on-the-wall" / "glossary.yaml"


def test_load_config_reads_yaml_overrides(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                "default_transcription_provider: speechmatics",
                "language: en",
                f"export_destination: {tmp_path / 'exports'}",
                "cleanup_mode: deterministic",
                "confidence_thresholds:",
                "  named: 0.82",
                "  uncertain: 0.67",
            ]
        )
    )

    config = load_config(config_path)

    assert config.default_transcription_provider == "speechmatics"
    assert config.language == "en"
    assert config.export_destination == tmp_path / "exports"
    assert config.cleanup_mode == "deterministic"
    assert config.confidence_thresholds.named == 0.82
    assert config.confidence_thresholds.uncertain == 0.67


def test_load_config_rejects_non_mapping_yaml(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text("- not\n- a\n- mapping\n")

    with pytest.raises(ConfigError, match="must be a YAML mapping"):
        load_config(config_path)


def test_get_api_key_reads_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    assert get_api_key("openai") == "test-key"


def test_get_api_key_returns_none_for_missing_or_unknown_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("keyring.get_password", lambda service, provider: None)

    assert get_api_key("openai") is None
    assert get_api_key("unknown") is None
