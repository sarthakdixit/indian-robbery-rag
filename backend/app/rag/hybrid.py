"""Hybrid retrieval fusion: combine vector and BM25 results via RRF.

Reciprocal Rank Fusion is a parameter-free way to combine ranked lists
from different retrievers. Each retriever contributes 1 / (k + rank) to
the fused score of each chunk; the constant k dampens top-rank dominance.

Pure functions only — no I/O, no async. Easy to unit test against fixed
inputs.
"""

from __future__ import annotations

from collections.abc import Iterable

from backend.app.protocols.retrieval import RetrievedChunk
from backend.app.rag.constants import RRF_K


def reciprocal_rank_fusion(
    *ranked_lists: Iterable[RetrievedChunk],
    k: int = RRF_K,
) -> list[RetrievedChunk]:
    """Fuse multiple ranked lists into a single ranked list using RRF.

    Each input list is treated as a ranking (position 0 is most relevant).
    A chunk's fused score is the sum of `1 / (k + rank_in_list_i)` across
    every list it appears in. Chunks appearing in only one list still get
    a meaningful score from that one contribution.

    The returned chunk objects preserve the metadata and text from the
    first list in which they appeared (since metadata is the same across
    retrievers — both BM25 and vector return the same underlying chunks
    from chunks.jsonl). Their `score` field is replaced with the fused
    RRF score, and their `source` field is set to "hybrid".

    Order is by descending fused score; ties broken by chunk_id for
    deterministic output (helps debugging and snapshot-safe testing).
    """
    if k < 1:
        raise ValueError(f"RRF k must be >= 1, got {k}")

    # chunk_id -> (best chunk object seen so far, accumulated rrf score)
    fused: dict[str, tuple[RetrievedChunk, float]] = {}

    for ranked_list in ranked_lists:
        for rank, chunk in enumerate(ranked_list):
            contribution = 1.0 / (k + rank)
            existing = fused.get(chunk.chunk_id)
            if existing is None:
                fused[chunk.chunk_id] = (chunk, contribution)
            else:
                fused[chunk.chunk_id] = (existing[0], existing[1] + contribution)

    rebuilt = [
        RetrievedChunk(
            chunk_id=chunk.chunk_id,
            text=chunk.text,
            score=rrf_score,
            source="hybrid",
            metadata=chunk.metadata,
        )
        for chunk, rrf_score in fused.values()
    ]

    rebuilt.sort(key=lambda c: (-c.score, c.chunk_id))
    return rebuilt