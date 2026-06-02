from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from sqlite3 import Connection
from uuid import uuid4

from fly_on_the_wall.config import ConfidenceThresholds
from fly_on_the_wall.embeddings import cosine_similarity, read_embedding


@dataclass(frozen=True)
class SpeakerMatch:
    local_speaker_id: str
    person_id: str | None
    status: str
    confidence: float | None
    margin: float | None


def match_local_speakers(
    connection: Connection,
    provider_run_id: str,
    thresholds: ConfidenceThresholds | None = None,
) -> list[SpeakerMatch]:
    resolved_thresholds = thresholds or ConfidenceThresholds()
    local_speakers = connection.execute(
        "SELECT id FROM local_speakers WHERE provider_run_id = ? ORDER BY label",
        (provider_run_id,),
    ).fetchall()

    matches: list[SpeakerMatch] = []
    for local_speaker in local_speakers:
        match = match_local_speaker(connection, local_speaker["id"], resolved_thresholds)
        _store_assignment(connection, match)
        matches.append(match)
    return matches


def match_local_speaker(
    connection: Connection,
    local_speaker_id: str,
    thresholds: ConfidenceThresholds,
) -> SpeakerMatch:
    local_embedding = connection.execute(
        """
        SELECT embedding_path FROM local_speaker_embeddings
        WHERE local_speaker_id = ?
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (local_speaker_id,),
    ).fetchone()
    if local_embedding is None:
        return SpeakerMatch(local_speaker_id, None, "unknown", None, None)

    local_vector = read_embedding(Path(local_embedding["embedding_path"]))
    scores = _score_people(connection, local_vector)
    if not scores:
        return SpeakerMatch(local_speaker_id, None, "unknown", None, None)

    best = scores[0]
    second_score = scores[1]["score"] if len(scores) > 1 else 0.0
    margin = best["score"] - second_score
    if best["score"] >= thresholds.named:
        status = "known"
        person_id = best["person_id"]
    elif best["score"] >= thresholds.uncertain:
        status = "uncertain"
        person_id = best["person_id"]
    else:
        status = "unknown"
        person_id = None
    return SpeakerMatch(local_speaker_id, person_id, status, best["score"], margin)


def _score_people(
    connection: Connection, local_vector: list[float]
) -> list[dict[str, float | str]]:
    rows = connection.execute(
        """
        SELECT person_id, id AS voice_sample_id, embedding_path
        FROM voice_samples
        WHERE embedding_path IS NOT NULL
        """
    ).fetchall()
    best_by_person: dict[str, dict[str, float | str]] = {}
    for row in rows:
        score = cosine_similarity(local_vector, read_embedding(Path(row["embedding_path"])))
        current = best_by_person.get(row["person_id"])
        if current is None or score > current["score"]:
            best_by_person[row["person_id"]] = {
                "person_id": row["person_id"],
                "voice_sample_id": row["voice_sample_id"],
                "score": score,
            }
    return sorted(best_by_person.values(), key=lambda item: item["score"], reverse=True)


def _store_assignment(connection: Connection, match: SpeakerMatch) -> None:
    existing = connection.execute(
        "SELECT evidence_json FROM speaker_assignments WHERE local_speaker_id = ?",
        (match.local_speaker_id,),
    ).fetchone()
    if existing is not None:
        try:
            evidence = json.loads(existing["evidence_json"])
        except json.JSONDecodeError:
            evidence = {}
        if evidence.get("method") == "user_correction":
            return

    with connection:
        connection.execute(
            """
            INSERT INTO speaker_assignments(
                id, local_speaker_id, person_id, status, confidence, margin, evidence_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(local_speaker_id) DO UPDATE SET
                person_id = excluded.person_id,
                status = excluded.status,
                confidence = excluded.confidence,
                margin = excluded.margin,
                evidence_json = excluded.evidence_json
            """,
            (
                str(uuid4()),
                match.local_speaker_id,
                match.person_id,
                match.status,
                match.confidence,
                match.margin,
                json.dumps({"method": "embedding_cosine"}),
            ),
        )
