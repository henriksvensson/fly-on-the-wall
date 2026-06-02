from __future__ import annotations

import hashlib
from pathlib import Path


def text_sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def read_cached_text(cache_dir: Path, cache_key: str) -> str | None:
    path = _cache_path(cache_dir, cache_key)
    if not path.exists():
        return None
    return path.read_text()


def write_cached_text(cache_dir: Path, cache_key: str, value: str) -> Path:
    path = _cache_path(cache_dir, cache_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value)
    return path


def _cache_path(cache_dir: Path, cache_key: str) -> Path:
    return cache_dir / f"{cache_key}.txt"
