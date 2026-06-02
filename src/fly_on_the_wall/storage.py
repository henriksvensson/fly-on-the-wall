from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from fly_on_the_wall.config import APP_DIR_NAME


@dataclass(frozen=True)
class StoragePaths:
    root: Path
    database: Path
    audio: Path
    artifacts: Path
    voice_samples: Path
    exports: Path

    @property
    def directories(self) -> tuple[Path, ...]:
        return (
            self.root,
            self.audio,
            self.artifacts,
            self.voice_samples,
            self.exports,
        )


def data_dir() -> Path:
    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    if xdg_data_home:
        return Path(xdg_data_home).expanduser() / APP_DIR_NAME
    return Path.home() / ".local" / "share" / APP_DIR_NAME


def storage_paths(root: Path | None = None) -> StoragePaths:
    storage_root = root or data_dir()
    return StoragePaths(
        root=storage_root,
        database=storage_root / "fly.db",
        audio=storage_root / "audio",
        artifacts=storage_root / "artifacts",
        voice_samples=storage_root / "voice-samples",
        exports=storage_root / "exports",
    )


def ensure_storage_layout(root: Path | None = None) -> StoragePaths:
    paths = storage_paths(root)
    for directory in paths.directories:
        directory.mkdir(parents=True, exist_ok=True)
    return paths
