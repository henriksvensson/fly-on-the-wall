from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

APP_DIR_NAME = "fly-on-the-wall"
CONFIG_FILE_NAME = "config.yaml"
GLOSSARY_FILE_NAME = "glossary.yaml"

ProviderName = Literal["elevenlabs", "openai"]
CleanupMode = Literal["off", "deterministic", "light"]

API_KEY_ENV_VARS: dict[str, str] = {
    "elevenlabs": "ELEVENLABS_API_KEY",
    "openai": "OPENAI_API_KEY",
}


class ConfigError(RuntimeError):
    """Raised when the application config cannot be loaded."""


class ConfidenceThresholds(BaseModel):
    model_config = ConfigDict(extra="forbid")

    named: float = Field(default=0.78, ge=0.0, le=1.0)
    uncertain: float = Field(default=0.62, ge=0.0, le=1.0)


class AppConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    default_transcription_provider: ProviderName = "elevenlabs"
    language: str = "sv"
    export_destination: Path | None = None
    confidence_thresholds: ConfidenceThresholds = Field(default_factory=ConfidenceThresholds)
    cleanup_mode: CleanupMode = "light"
    glossary_path: Path | None = None


def config_dir() -> Path:
    xdg_config_home = os.environ.get("XDG_CONFIG_HOME")
    if xdg_config_home:
        return Path(xdg_config_home).expanduser() / APP_DIR_NAME
    return Path.home() / ".config" / APP_DIR_NAME


def default_config_path() -> Path:
    return config_dir() / CONFIG_FILE_NAME


def default_glossary_path() -> Path:
    return config_dir() / GLOSSARY_FILE_NAME


def load_config(path: Path | None = None) -> AppConfig:
    config_path = path or default_config_path()
    data = _read_yaml_mapping(config_path)

    if "glossary_path" not in data:
        data["glossary_path"] = default_glossary_path()

    try:
        return AppConfig.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(f"Invalid config at {config_path}: {exc}") from exc


def get_api_key(provider: str) -> str | None:
    from fly_on_the_wall.secrets import get_api_key as get_secret_api_key

    return get_secret_api_key(provider)


def _read_yaml_mapping(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}

    try:
        content = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML at {path}: {exc}") from exc

    if content is None:
        return {}
    if not isinstance(content, dict):
        raise ConfigError(f"Config at {path} must be a YAML mapping.")
    return content
