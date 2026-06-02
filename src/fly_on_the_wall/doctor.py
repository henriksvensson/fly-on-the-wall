from __future__ import annotations

import sys
from dataclasses import dataclass
from shutil import which

from fly_on_the_wall.config import API_KEY_ENV_VARS, default_config_path, load_config
from fly_on_the_wall.storage import storage_paths


@dataclass(frozen=True)
class DoctorCheck:
    name: str
    ok: bool
    detail: str


def run_checks() -> list[DoctorCheck]:
    paths = storage_paths()
    checks = [
        DoctorCheck(
            name="python",
            ok=sys.version_info >= (3, 12),
            detail=f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        ),
        DoctorCheck(
            name="ffmpeg",
            ok=which("ffmpeg") is not None,
            detail=which("ffmpeg") or "not found",
        ),
        DoctorCheck(
            name="config path",
            ok=True,
            detail=str(default_config_path()),
        ),
        DoctorCheck(
            name="storage path",
            ok=True,
            detail=str(paths.root),
        ),
    ]

    config = load_config()
    provider = config.default_transcription_provider
    env_var = API_KEY_ENV_VARS[provider]
    checks.append(
        DoctorCheck(
            name=f"{provider} api key",
            ok=_env_has_value(env_var),
            detail=f"{env_var} is {'set' if _env_has_value(env_var) else 'not set'}",
        )
    )
    checks.append(
        DoctorCheck(
            name="openai api key",
            ok=_env_has_value("OPENAI_API_KEY"),
            detail=f"OPENAI_API_KEY is {'set' if _env_has_value('OPENAI_API_KEY') else 'not set'}",
        )
    )
    return checks


def _env_has_value(name: str) -> bool:
    from os import environ

    return bool(environ.get(name))


def has_failures(checks: list[DoctorCheck]) -> bool:
    return any(not check.ok for check in checks)


def check_names(checks: list[DoctorCheck]) -> set[str]:
    return {check.name for check in checks}
