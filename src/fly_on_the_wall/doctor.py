from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass
from shutil import which

from fly_on_the_wall.config import default_config_path, load_config
from fly_on_the_wall.db import database
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
    checks.extend(_speaker_embedding_checks())
    return checks


def _speaker_embedding_checks() -> list[DoctorCheck]:
    pyannote_available = _module_available("pyannote.audio")
    counts = _speaker_embedding_counts()
    return [
        DoctorCheck(
            name="pyannote.audio",
            ok=pyannote_available,
            detail=(
                "available for speaker embeddings"
                if pyannote_available
                else "missing; install pyannote.audio, torch, and torchaudio"
            ),
        ),
        DoctorCheck(
            name="voice sample embeddings",
            ok=counts["voice_samples"] == 0 or counts["embedded_voice_samples"] == counts["voice_samples"],
            detail=(f"{counts['embedded_voice_samples']}/{counts['voice_samples']} " "voice samples embedded"),
        ),
        DoctorCheck(
            name="local speaker embeddings",
            ok=counts["local_speakers"] == 0 or counts["embedded_local_speakers"] > 0 or pyannote_available,
            detail=(f"{counts['embedded_local_speakers']}/{counts['local_speakers']} " "local speakers embedded"),
        ),
    ]


def _speaker_embedding_counts() -> dict[str, int]:
    with database() as connection:
        voice = connection.execute(
            """
            SELECT COUNT(*) AS total,
                   SUM(CASE WHEN embedding_path IS NOT NULL THEN 1 ELSE 0 END) AS embedded
            FROM voice_samples
            """
        ).fetchone()
        local = connection.execute(
            """
            SELECT COUNT(DISTINCT local_speakers.id) AS total,
                   COUNT(DISTINCT local_speaker_embeddings.local_speaker_id) AS embedded
            FROM local_speakers
            LEFT JOIN local_speaker_embeddings
                ON local_speaker_embeddings.local_speaker_id = local_speakers.id
            """
        ).fetchone()
    return {
        "voice_samples": int(voice["total"] or 0),
        "embedded_voice_samples": int(voice["embedded"] or 0),
        "local_speakers": int(local["total"] or 0),
        "embedded_local_speakers": int(local["embedded"] or 0),
    }


def _module_available(module_name: str) -> bool:
    try:
        return importlib.util.find_spec(module_name) is not None
    except ModuleNotFoundError:
        return False


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
