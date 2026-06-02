from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path
from select import select


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


def play_audio(audio_path: Path, player: str = "ffplay", stop_on_enter: bool = False) -> None:
    if player == "ffplay":
        command = ["ffplay", "-nodisp", "-autoexit", str(audio_path)]
    else:
        command = [player, str(audio_path)]
    if stop_on_enter:
        _run_until_enter(command)
        return
    _run(command)


def _run_until_enter(command: list[str]) -> None:
    try:
        process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except FileNotFoundError as exc:
        raise AudioError(f"Required audio tool not found: {command[0]}") from exc

    try:
        while process.poll() is None:
            if sys.stdin.isatty():
                ready, _, _ = select([sys.stdin], [], [], 0.1)
                if ready:
                    sys.stdin.readline()
                    process.terminate()
                    break
            else:
                time.sleep(0.1)
    except KeyboardInterrupt:
        process.terminate()
    finally:
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(command, check=True, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise AudioError(f"Required audio tool not found: {command[0]}") from exc
    except subprocess.CalledProcessError as exc:
        message = exc.stderr.strip() or exc.stdout.strip() or str(exc)
        raise AudioError(f"Audio command failed: {message}") from exc
