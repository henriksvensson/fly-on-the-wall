from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from sqlite3 import Connection
from typing import Any
from uuid import uuid4

import yaml

UNSUPPORTED_KEYTERM_CHARS = set("<>{}[]\\")


@dataclass(frozen=True)
class GlossaryTerm:
    id: str
    term: str
    description: str | None
    enabled: bool


def create_glossary_term(connection: Connection, term: str, description: str | None = None) -> GlossaryTerm:
    normalized = _normalize_term(term)
    normalized_description = _normalize_optional(description)
    term_id = str(uuid4())
    with connection:
        connection.execute(
            """
            INSERT INTO glossary_terms(id, term, description)
            VALUES (?, ?, ?)
            """,
            (term_id, normalized, normalized_description),
        )
    return get_glossary_term(connection, normalized)  # type: ignore[return-value]


def get_glossary_term(connection: Connection, term_or_id: str) -> GlossaryTerm | None:
    row = connection.execute(
        """
        SELECT * FROM glossary_terms
        WHERE id = ? OR term = ?
        """,
        (term_or_id, term_or_id),
    ).fetchone()
    return _term_from_row(row) if row is not None else None


def list_glossary_terms(connection: Connection, include_disabled: bool = False) -> list[GlossaryTerm]:
    query = "SELECT * FROM glossary_terms"
    if not include_disabled:
        query += " WHERE enabled = 1"
    query += " ORDER BY lower(term)"
    return [_term_from_row(row) for row in connection.execute(query).fetchall()]


def update_glossary_term(
    connection: Connection,
    term_or_id: str,
    *,
    term: str | None = None,
    description: str | None = None,
    enabled: bool | None = None,
) -> GlossaryTerm:
    existing = get_glossary_term(connection, term_or_id)
    if existing is None:
        raise ValueError(f"Glossary term not found: {term_or_id}")

    updated_term = existing.term if term is None else _normalize_term(term)
    updated_description = existing.description if description is None else _normalize_optional(description)
    updated_enabled = existing.enabled if enabled is None else enabled
    with connection:
        connection.execute(
            """
            UPDATE glossary_terms
            SET term = ?,
                description = ?,
                enabled = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (updated_term, updated_description, int(updated_enabled), existing.id),
        )
    return get_glossary_term(connection, existing.id)  # type: ignore[return-value]


def remove_glossary_term(connection: Connection, term_or_id: str) -> bool:
    existing = get_glossary_term(connection, term_or_id)
    if existing is None:
        return False
    with connection:
        connection.execute("DELETE FROM glossary_terms WHERE id = ?", (existing.id,))
    return True


def glossary_prompt_lines(connection: Connection, legacy_glossary_path: Path | None = None) -> list[str]:
    lines: list[str] = []
    seen: set[str] = set()

    for item in list_glossary_terms(connection):
        key = item.term.casefold()
        if key in seen:
            continue
        seen.add(key)
        if item.description:
            lines.append(f"{item.term}: {item.description}")
        else:
            lines.append(item.term)

    for term in load_glossary_terms(legacy_glossary_path):
        key = term.casefold()
        if key not in seen:
            seen.add(key)
            lines.append(term)

    for name in _people_names(connection):
        key = name.casefold()
        if key not in seen:
            seen.add(key)
            lines.append(name)

    return lines


def transcription_keyterms(connection: Connection, legacy_glossary_path: Path | None = None) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()
    for item in list_glossary_terms(connection):
        _append_keyterm(terms, seen, item.term)
    for term in load_glossary_terms(legacy_glossary_path):
        _append_keyterm(terms, seen, term)
    for name in _people_names(connection):
        _append_keyterm(terms, seen, name)
    return terms[:1000]


def load_glossary_terms(path: Path | None) -> list[str]:
    if path is None or not path.exists():
        return []
    data = yaml.safe_load(path.read_text())
    return sorted(set(_collect_terms(data)), key=str.casefold)


def _append_keyterm(terms: list[str], seen: set[str], value: str) -> None:
    normalized = " ".join(value.split())
    key = normalized.casefold()
    if key in seen or not _valid_keyterm(normalized):
        return
    seen.add(key)
    terms.append(normalized)


def _valid_keyterm(value: str) -> bool:
    return (
        bool(value)
        and len(value) < 50
        and len(value.split()) <= 5
        and not any(char in value for char in UNSUPPORTED_KEYTERM_CHARS)
    )


def _people_names(connection: Connection) -> list[str]:
    return [
        str(row["display_name"])
        for row in connection.execute("SELECT display_name FROM people ORDER BY lower(display_name)").fetchall()
    ]


def _normalize_term(value: str) -> str:
    normalized = " ".join(value.split())
    if not normalized:
        raise ValueError("Glossary term cannot be empty")
    return normalized


def _normalize_optional(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = " ".join(value.split())
    return normalized or None


def _term_from_row(row: Any) -> GlossaryTerm:
    return GlossaryTerm(
        id=row["id"],
        term=row["term"],
        description=row["description"],
        enabled=bool(row["enabled"]),
    )


def _collect_terms(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        normalized = " ".join(value.split())
        return [normalized] if normalized else []
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
