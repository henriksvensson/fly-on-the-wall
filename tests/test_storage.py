from pathlib import Path

import pytest

from fly_on_the_wall.storage import data_dir, ensure_storage_layout, storage_paths


def test_data_dir_uses_xdg_data_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data-home"))

    assert data_dir() == tmp_path / "data-home" / "fly-on-the-wall"


def test_storage_paths_uses_expected_layout(tmp_path: Path) -> None:
    paths = storage_paths(tmp_path)

    assert paths.root == tmp_path
    assert paths.database == tmp_path / "fly.db"
    assert paths.audio == tmp_path / "audio"
    assert paths.artifacts == tmp_path / "artifacts"
    assert paths.voice_samples == tmp_path / "voice-samples"
    assert paths.exports == tmp_path / "exports"


def test_ensure_storage_layout_creates_directories(tmp_path: Path) -> None:
    paths = ensure_storage_layout(tmp_path)

    assert all(directory.is_dir() for directory in paths.directories)
    assert not paths.database.exists()


def test_ensure_storage_layout_is_idempotent(tmp_path: Path) -> None:
    ensure_storage_layout(tmp_path)
    paths = ensure_storage_layout(tmp_path)

    assert all(directory.is_dir() for directory in paths.directories)
