import subprocess
from pathlib import Path

import pytest

from fly_on_the_wall import audio


def test_get_duration_uses_ffprobe(monkeypatch: pytest.MonkeyPatch) -> None:
    commands: list[list[str]] = []

    def fake_run(command: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="12.5\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert audio.get_duration(Path("meeting.m4a")) == 12.5
    assert commands[0][0] == "ffprobe"


def test_normalize_for_embedding_builds_expected_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    commands: list[list[str]] = []

    def fake_run(command: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    output = audio.normalize_for_embedding(Path("in.m4a"), tmp_path / "out.wav")

    assert output == tmp_path / "out.wav"
    assert commands[0] == [
        "ffmpeg",
        "-y",
        "-i",
        "in.m4a",
        "-ac",
        "1",
        "-ar",
        "16000",
        str(tmp_path / "out.wav"),
    ]


def test_extract_clip_rejects_invalid_range(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="greater than start"):
        audio.extract_clip(Path("in.m4a"), tmp_path / "clip.wav", 5.0, 4.0)


def test_audio_error_wraps_missing_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(command: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError(command[0])

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(audio.AudioError, match="Required audio tool not found"):
        audio.convert_to_wav(Path("in.m4a"), Path("out.wav"))
