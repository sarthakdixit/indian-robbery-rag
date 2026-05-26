"""Protocols (interfaces) for retrieval-side dependencies.

Per AGENT.md §3, business logic depends only on these Protocols, never on
concrete adapters. The DI container in Batch 3.4 wires concrete adapters
based on `Settings.environment`.

Three protocols here cover the retrieval stage:
  - EmbeddingsClient — embeds a single query string (vs the bulk ingestion
    embedder which embeds documents). Uses RETRIEVAL_QUERY task_type.
  - VectorStore — nearest-neighbour search by query embedding.
  - BM25Searcher — keyword search by tokenized query.

Generation, document store (cache + logs), and secrets get their own
protocols in later chunks once we need them.

DTOs (RetrievedChunk, ScoredChunk) are dataclasses rather than Pydantic
models because they never cross an HTTP boundary — per AGENT.md §12.2,
internal value objects can skip Pydantic's validation overhead.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class RetrievedChunk:
    """A chunk pulled from the index, plus the score that surfaced it.

    `score` is interpreted in context: for vector retrieval it's cosine
    similarity (0..1, higher = better); for BM25 it's the raw BM25 score
    (unbounded, higher = better). The hybrid retriever normalizes both
    onto a comparable scale before fusing.
    """

    chunk_id: str
    text: str
    score: float
    source: str  # "vector" | "bm25" | "hybrid"
    metadata: dict[str, Any] = field(default_factory=dict)


class EmbeddingsClient(Protocol):
    """Embeds a single query string with task_type=RETRIEVAL_QUERY.

    Ingestion uses task_type=RETRIEVAL_DOCUMENT; the asymmetry is
    deliberate and improves retrieval relevance (see Batch 2.1 README).
    """

    async def embed_query(self, query: str) -> list[float]:
        """Return a unit-normalized embedding vector for the query."""
        ...


class VectorStore(Protocol):
    """Nearest-neighbour search by query embedding."""

    async def search(
        self,
        query_embedding: list[float],
        top_k: int,
        where: dict[str, Any] | None = None,
    ) -> list[RetrievedChunk]:
        """Return the top_k nearest chunks by cosine similarity.

        `where` is a backend-specific metadata filter (e.g., for ChromaDB,
        `{"source_type": "act"}`). None means no filter. Implementations
        translate this to their native filter syntax.

        `score` on returned chunks is cosine similarity in [0, 1] —
        ChromaDB returns cosine *distance* (1 - similarity) which the
        adapter converts.
        """
        ...

    async def count(self) -> int:
        """Return the number of indexed chunks. Used at startup for health
        checks and by the scope-rejection heuristic for sanity logging."""
        ...


class BM25Searcher(Protocol):
    """Keyword search via BM25 over tokenized chunk texts."""

    async def search(self, query: str, top_k: int) -> list[RetrievedChunk]:
        """Return the top_k chunks by BM25 score.

        The query string is tokenized internally using the same tokenizer
        as the ingestion-time builder (lowercase, alphanumeric split,
        `§` -> `section`). Score is the raw BM25 value; the hybrid
        retriever normalizes before fusion.
        """
        ...