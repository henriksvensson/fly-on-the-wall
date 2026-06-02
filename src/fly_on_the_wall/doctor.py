from __future__ import annotations

import sys
from dataclasses import dataclass
from shutil import which

from fly_on_the_wall.config import default_config_path, load_config
from fly_on_the_wall.secrets import get_api_key_status
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
    provider_status = get_api_key_status(provider)
    checks.append(
        DoctorCheck(
            name=f"{provider} api key",
            ok=provider_status.available,
            detail=_secret_detail(provider_status.source, provider_status.env_var),
        )
    )
    openai_status = get_api_key_status("openai")
    checks.append(
        DoctorCheck(
            name="openai api key",
            ok=openai_status.available,
            detail=_secret_detail(openai_status.source, openai_status.env_var),
        )
    )
    return checks


def _secret_detail(source: str, env_var: str | None) -> str:
    if source == "env":
        return f"{env_var} is set"
    if source == "keyring":
        return "set in OS keyring"
    if source == "missing":
        return f"{env_var} is not set and no keyring entry was found"
    return "unknown provider"


def has_failures(checks: list[DoctorCheck]) -> bool:
    return any(not check.ok for check in checks)


def check_names(checks: list[DoctorCheck]) -> set[str]:
    return {check.name for check in checks}
