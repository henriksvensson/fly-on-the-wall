from __future__ import annotations

import json
import math
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from sqlite3 import Connection
from typing import Protocol, runtime_checkable
from uuid import uuid4

from fly_on_the_wall.storage import StoragePaths, storage_paths

DEFAULT_EMBEDDING_MODEL = "pyannote/wespeaker-voxceleb-resnet34-LM"


class EmbeddingBackend(Protocol):
    model_name: str

    def embed(self, audio_path: Path) -> list[float]: ...


@runtime_checkable
class SupportsToList(Protocol):
    def tolist(self) -> object: ...


@dataclass(frozen=True)
class CachedEmbedding:
    model_name: str
    path: Path
    vector: list[float]


class PyannoteEmbeddingBackend:
    model_name = DEFAULT_EMBEDDING_MODEL

    def __init__(self) -> None:
        try:
            from pyannote.audio import Inference, Model
        except ImportError as exc:
            raise RuntimeError("pyannote.audio is required for local speaker embeddings.") from exc

        model = Model.from_pretrained(self.model_name)
        if model is None:
            raise RuntimeError(f"Could not load embedding model: {self.model_name}")
        self._inference = Inference(model, window="whole")

    def embed(self, audio_path: Path) -> list[float]:
        return _embedding_to_vector(self._inference(str(audio_path)))


def _embedding_to_vector(embedding: object) -> list[float]:
    values = embedding.tolist() if isinstance(embedding, SupportsToList) else embedding
    if isinstance(values, str | bytes | bytearray) or not isinstance(values, Iterable):
        raise RuntimeError("Embedding backend returned an unsupported shape.")
    try:
        return [_embedding_value_to_float(value) for value in values]
    except (TypeError, ValueError) as exc:
        raise RuntimeError("Embedding backend returned non-numeric values.") from exc


def _embedding_value_to_float(value: object) -> float:
    if not isinstance(value, int | float | str | bytes | bytearray):
        raise TypeError(f"Unsupported embedding value: {type(value).__name__}")
    return float(value)


def cache_voice_sample_embedding(
    connection: Connection,
    voice_sample_id: str,
    backend: EmbeddingBackend,
    storage: StoragePaths | None = None,
) -> CachedEmbedding:
    sample = connection.execute(
        "SELECT person_id, audio_path FROM voice_samples WHERE id = ?", (voice_sample_id,)
    ).fetchone()
    if sample is None:
        raise ValueError(f"Voice sample does not exist: {voice_sample_id}")

    paths = storage or storage_paths()
    vector = backend.embed(Path(sample["audio_path"]))
    embedding_path = _write_embedding(
        paths.artifacts / "embeddings" / "voice-samples" / sample["person_id"],
        voice_sample_id,
        backend.model_name,
        vector,
    )

    with connection:
        connection.execute(
            """
            UPDATE voice_samples
            SET embedding_model = ?, embedding_path = ?
            WHERE id = ?
            """,
            (backend.model_name, str(embedding_path), voice_sample_id),
        )
    return CachedEmbedding(backend.model_name, embedding_path, vector)


def cache_local_speaker_embedding(
    connection: Connection,
    local_speaker_id: str,
    audio_path: Path,
    backend: EmbeddingBackend,
    storage: StoragePaths | None = None,
) -> CachedEmbedding:
    if connection.execute("SELECT 1 FROM local_speakers WHERE id = ?", (local_speaker_id,)).fetchone() is None:
        raise ValueError(f"Local speaker does not exist: {local_speaker_id}")

    paths = storage or storage_paths()
    vector = backend.embed(audio_path)
    embedding_path = _write_embedding(
        paths.artifacts / "embeddings" / "local-speakers",
        local_speaker_id,
        backend.model_name,
        vector,
    )
    embedding_id = str(uuid4())
    with connection:
        connection.execute(
            """
            INSERT INTO local_speaker_embeddings(
                id, local_speaker_id, audio_path, embedding_model, embedding_path
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(local_speaker_id, embedding_model) DO UPDATE SET
                audio_path = excluded.audio_path,
                embedding_path = excluded.embedding_path
            """,
            (
                embedding_id,
                local_speaker_id,
                str(audio_path),
                backend.model_name,
                str(embedding_path),
            ),
        )
    return CachedEmbedding(backend.model_name, embedding_path, vector)


def read_embedding(path: Path) -> list[float]:
    data = json.loads(path.read_text())
    return [float(value) for value in data["vector"]]


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        raise ValueError("Embedding vectors must have the same length.")
    numerator = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return numerator / (left_norm * right_norm)


def _write_embedding(directory: Path, source_id: str, model_name: str, vector: list[float]) -> Path:
    safe_model_name = model_name.replace("/", "--")
    path = directory / f"{source_id}.{safe_model_name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"model": model_name, "vector": vector}) + "\n")
    return path
