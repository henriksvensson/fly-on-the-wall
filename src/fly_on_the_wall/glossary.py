from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def load_glossary_terms(path: Path | None) -> list[str]:
    if path is None or not path.exists():
        return []
    data = yaml.safe_load(path.read_text())
    return sorted(set(_collect_terms(data)))


def _collect_terms(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        terms: list[str] = []
        for item in value:
            terms.extend(_collect_terms(item))
        return terms
    if isinstance(value, dict):
        terms = []
        for item in value.values():
            terms.extend(_collect_terms(item))
        return terms
    return []
