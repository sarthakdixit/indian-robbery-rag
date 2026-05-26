"""Top-level retrieval orchestrator.

The `Retriever` class composes the four protocols from `clients/` into a
single end-to-end "query in, ranked chunks out" function. It also enforces
the out-of-scope rejection policy: queries whose top retrieved chunk's
vector similarity is below the threshold are rejected without consuming
LLM quota.

Returned types are a small discriminated outcome rather than raising for
the OOS case, because OOS is not an error condition — it's an expected,
common outcome that the frontend renders with a specific UI panel
(suggested questions instead of an answer).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from backend.app.protocols.retrieval import (
    BM25Searcher,
    EmbeddingsClient,
    RetrievedChunk,
    VectorStore,
)
from backend.app.rag.constants import (
    OUT_OF_SCOPE_EXAMPLE_QUERIES,
    RETRIEVAL_FINAL_K,
    RETRIEVAL_TOP_K,
    SCOPE_REJECTION_SIMILARITY_THRESHOLD,
)
from backend.app.rag.hybrid import reciprocal_rank_fusion

if TYPE_CHECKING:
    pass


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RetrievalSuccess:
    """The query was in-scope; here are the top-K chunks for the LLM."""

    chunks: list[RetrievedChunk]
    top_vector_similarity: float


@dataclass(frozen=True)
class RetrievalOutOfScope:
    """The query was rejected as out-of-scope before the LLM was called.

    `top_vector_similarity` records what the actual top similarity was,
    useful for logging and for debugging false rejections.

    `suggestions` is the curated list of in-scope example queries to show
    the user instead of an answer.
    """

    top_vector_similarity: float
    suggestions: tuple[str, ...]


RetrievalOutcome = RetrievalSuccess | RetrievalOutOfScope


class Retriever:
    """End-to-end query -> ranked chunks orchestrator.

    Constructor takes the three protocol implementations rather than the
    DI container directly; this keeps `Retriever` testable with simple
    fakes (no container required).

    The scope threshold and top-K values are constructor parameters with
    sensible defaults so tests can dial them down (e.g., threshold=0.0
    to disable scope check, top_k=2 for fast tests).
    """

    def __init__(
        self,
        embeddings: EmbeddingsClient,
        vector_store: VectorStore,
        bm25: BM25Searcher,
        top_k: int = RETRIEVAL_TOP_K,
        final_k: int = RETRIEVAL_FINAL_K,
        scope_threshold: float = SCOPE_REJECTION_SIMILARITY_THRESHOLD,
        out_of_scope_examples: tuple[str, ...] = OUT_OF_SCOPE_EXAMPLE_QUERIES,
    ) -> None:
        self._embeddings = embeddings
        self._vector_store = vector_store
        self._bm25 = bm25
        self._top_k = top_k
        self._final_k = final_k
        self._scope_threshold = scope_threshold
        self._oos_examples = out_of_scope_examples

    async def retrieve(self, query: str) -> RetrievalOutcome:
        """Run the full retrieval pipeline for a single query."""
        query_embedding = await self._embeddings.embed_query(query)

        vector_hits = await self._vector_store.search(query_embedding, top_k=self._top_k)
        bm25_hits = await self._bm25.search(query, top_k=self._top_k)

        # Scope check uses the BEST vector similarity, not the fused score.
        # Reasoning: BM25 can give high keyword-overlap scores to off-topic
        # chunks that happen to share rare terms. Vector similarity is the
        # more reliable semantic-relevance signal at the top-1 boundary.
        # If vector retrieval returns nothing (e.g., partial index in dev),
        # fall back to top BM25 hit existence as a softer check.
        top_vector_similarity = max(
            (h.score for h in vector_hits if h.source == "vector"),
            default=0.0,
        )

        if not vector_hits and not bm25_hits:
            logger.info("retrieval: empty result set; rejecting as OOS")
            return RetrievalOutOfScope(
                top_vector_similarity=0.0,
                suggestions=self._oos_examples,
            )

        if vector_hits and top_vector_similarity < self._scope_threshold:
            logger.info(
                "retrieval: rejecting OOS (top vec sim %.3f < threshold %.3f)",
                top_vector_similarity, self._scope_threshold,
            )
            return RetrievalOutOfScope(
                top_vector_similarity=top_vector_similarity,
                suggestions=self._oos_examples,
            )

        fused = reciprocal_rank_fusion(vector_hits, bm25_hits)
        final = fused[: self._final_k]

        logger.info(
            "retrieval: %d vector + %d bm25 -> %d fused -> %d final "
            "(top_vec_sim=%.3f, top_fused=%.4f)",
            len(vector_hits), len(bm25_hits), len(fused), len(final),
            top_vector_similarity, final[0].score if final else 0.0,
        )

        return RetrievalSuccess(
            chunks=final,
            top_vector_similarity=top_vector_similarity,
        )