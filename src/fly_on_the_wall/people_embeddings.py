from __future__ import annotations

from dataclasses import dataclass
from sqlite3 import Connection

from fly_on_the_wall.embeddings import (
    EmbeddingBackend,
    PyannoteEmbeddingBackend,
    cache_voice_sample_embedding,
)
from fly_on_the_wall.storage import StoragePaths


@dataclass(frozen=True)
class PeopleEmbeddingStatus:
    people: int
    voice_samples: int
    embedded_voice_samples: int
    missing_voice_sample_embeddings: int


@dataclass(frozen=True)
class PeopleEmbeddingBackfillResult:
    embedded: int
    failed: int


def people_embedding_status(connection: Connection) -> PeopleEmbeddingStatus:
    people = connection.execute("SELECT COUNT(*) FROM people").fetchone()[0]
    voice = connection.execute(
        """
        SELECT COUNT(*) AS total,
               SUM(CASE WHEN embedding_path IS NOT NULL THEN 1 ELSE 0 END) AS embedded
        FROM voice_samples
        """
    ).fetchone()
    total = int(voice["total"] or 0)
    embedded = int(voice["embedded"] or 0)
    return PeopleEmbeddingStatus(
        people=int(people),
        voice_samples=total,
        embedded_voice_samples=embedded,
        missing_voice_sample_embeddings=total - embedded,
    )


def backfill_people_embeddings(
    connection: Connection,
    storage: StoragePaths | None = None,
    backend: EmbeddingBackend | None = None,
) -> PeopleEmbeddingBackfillResult:
    resolved_backend = backend or PyannoteEmbeddingBackend()
    rows = connection.execute(
        """
        SELECT id FROM voice_samples
        WHERE embedding_path IS NULL
        ORDER BY created_at
        """
    ).fetchall()
    embedded = failed = 0
    for row in rows:
        try:
            cache_voice_sample_embedding(connection, row["id"], resolved_backend, storage)
        except (FileNotFoundError, RuntimeError, ValueError):
            failed += 1
            continue
        embedded += 1
    return PeopleEmbeddingBackfillResult(embedded=embedded, failed=failed)
