from __future__ import annotations

import subprocess
from pathlib import Path


class AudioError(RuntimeError):
    """Raised when an audio operation fails."""


def get_duration(audio_path: Path) -> float:
    result = _run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(audio_path),
        ]
    )
    try:
        return float(result.stdout.strip())
    except ValueError as exc:
        raise AudioError(f"Could not read duration for {audio_path}") from exc


def convert_to_wav(input_path: Path, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _run(["ffmpeg", "-y", "-i", str(input_path), str(output_path)])
    return output_path


def normalize_for_embedding(input_path: Path, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(input_path),
            "-ac",
            "1",
            "-ar",
            "16000",
            str(output_path),
        ]
    )
    return output_path


def extract_clip(input_path: Path, output_path: Path, start: float, end: float) -> Path:
    if end <= start:
        raise ValueError("Clip end must be greater than start.")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    _run(
        [
            "ffmpeg",
            "-y",
            "-ss",
            f"{max(0.0, start):.3f}",
            "-to",
            f"{end:.3f}",
            "-i",
            str(input_path),
            str(output_path),
        ]
    )
    return output_path


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(command, check=True, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise AudioError(f"Required audio tool not found: {command[0]}") from exc
    except subprocess.CalledProcessError as exc:
        message = exc.stderr.strip() or exc.stdout.strip() or str(exc)
        raise AudioError(f"Audio command failed: {message}") from exc
