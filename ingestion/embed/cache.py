"""SQLite-backed embedding cache.

Stores `text -> embedding` for the duration of the ingestion process and
across runs. The cache key is a SHA-256 of the (text, model, task_type)
tuple so changing the model or task_type invalidates only the affected
entries — texts re-embedded under a different model don't conflict with
prior embeddings.

Why SQLite over JSONL or pickle:
  - O(1) lookups by hash (we hit this every batch)
  - Atomic writes; safe to ctrl-C mid-run without corrupting the cache
  - Concurrent reads if we ever want to parallelize embedding
  - Single file, no separate index, no schema migrations needed

The vector itself is stored as a binary blob (struct-packed float32 array)
rather than as text or JSON. For text-embedding-004 default dimensionality
of 768, that's 3 KB per embedding vs ~9 KB as a JSON list of floats.
"""

from __future__ import annotations

import hashlib
import sqlite3
import struct
from pathlib import Path


SCHEMA_VERSION: int = 1


def hash_text(text: str, model: str, task_type: str) -> str:
    """Return a deterministic cache key for the (text, model, task_type) triple."""
    payload = f"{model}\x00{task_type}\x00{text}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _pack_vector(vector: list[float]) -> bytes:
    return struct.pack(f"{len(vector)}f", *vector)


def _unpack_vector(blob: bytes) -> list[float]:
    count = len(blob) // 4
    return list(struct.unpack(f"{count}f", blob))


class EmbeddingCache:
    """SQLite-backed (text, model, task_type) -> embedding cache."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path))
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS embeddings (
                content_hash TEXT PRIMARY KEY,
                model TEXT NOT NULL,
                task_type TEXT NOT NULL,
                dim INTEGER NOT NULL,
                vector BLOB NOT NULL,
                created_at REAL NOT NULL DEFAULT (strftime('%s','now'))
            );
            CREATE INDEX IF NOT EXISTS idx_model_task ON embeddings(model, task_type);
            """
        )
        self._conn.commit()

    def get(self, text: str, model: str, task_type: str) -> list[float] | None:
        key = hash_text(text, model, task_type)
        row = self._conn.execute(
            "SELECT vector FROM embeddings WHERE content_hash = ?", (key,)
        ).fetchone()
        return _unpack_vector(row[0]) if row else None

    def put(self, text: str, model: str, task_type: str, vector: list[float]) -> None:
        key = hash_text(text, model, task_type)
        self._conn.execute(
            "INSERT OR REPLACE INTO embeddings "
            "(content_hash, model, task_type, dim, vector) VALUES (?, ?, ?, ?, ?)",
            (key, model, task_type, len(vector), _pack_vector(vector)),
        )
        self._conn.commit()

    def put_many(
        self,
        items: list[tuple[str, list[float]]],
        model: str,
        task_type: str,
    ) -> None:
        """Bulk insert. items is a list of (text, vector) pairs."""
        rows = [
            (hash_text(text, model, task_type), model, task_type, len(vec), _pack_vector(vec))
            for text, vec in items
        ]
        self._conn.executemany(
            "INSERT OR REPLACE INTO embeddings "
            "(content_hash, model, task_type, dim, vector) VALUES (?, ?, ?, ?, ?)",
            rows,
        )
        self._conn.commit()

    def count(self, model: str | None = None, task_type: str | None = None) -> int:
        if model is None and task_type is None:
            row = self._conn.execute("SELECT COUNT(*) FROM embeddings").fetchone()
        elif model is not None and task_type is not None:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM embeddings WHERE model = ? AND task_type = ?",
                (model, task_type),
            ).fetchone()
        else:
            raise ValueError("specify both model and task_type, or neither")
        return int(row[0])

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> EmbeddingCache:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()