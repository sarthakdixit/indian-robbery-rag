"""End-to-end RAG pipeline.

`Pipeline.answer(query)` orchestrates the full happy path:

  1. Normalize and exact-cache lookup (Chunk 3.4 — this file).
  2. Retrieve hybrid (Chunk 3.2 — `Retriever`).
  3. Scope check (Chunk 3.2 — returned as a discriminated outcome).
  4. Generate answer (Chunk 3.3 — `Generator`).
  5. Cache the response.
  6. Build and return the response envelope.

What's NOT here yet (each is its own concern, lands in Batch 4):

  - Semantic cache (Cosmos-backed; needs the document store).
  - Rate limiting / global cap / circuit breaker.
  - Query logging to Cosmos.
  - Citation verification (already done by `Generator` — re-doing here
    would be redundant).
  - HTTP routing (Batch 4's `routes/query.py` wraps Pipeline).

The `__main__` block at the bottom is the Batch 3 verification target:

    python -m backend.app.rag.pipeline "What is robbery under BNS?"

prints a JSON response to stdout. Exits 0 on success or out-of-scope,
non-zero on infrastructure failure.
"""

from __future__ import annotations

import json
import logging
import sys
import time
import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field

from backend.app.cache.exact_cache import CachedAnswer, ExactAnswerCache
from backend.app.protocols.retrieval import RetrievedChunk
from backend.app.rag.generate import Generator
from backend.app.rag.retrieval import (
    RetrievalOutcome,
    RetrievalOutOfScope,
    RetrievalSuccess,
    Retriever,
)


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Response models.
# ---------------------------------------------------------------------------
# These mirror the frontend's Zod schemas (see AGENT-frontend.md §8.2)
# verbatim. The HTTP layer in Batch 4 reuses them as FastAPI
# `response_model`, which auto-generates the OpenAPI schema the frontend's
# typed API client consumes.
class CitationCard(BaseModel):
    """One citation card, rendered alongside the answer text."""

    index: int = Field(ge=1)
    source_type: Literal["act", "judgment"]
    citation: str
    excerpt: str
    source_url: str | None = None
    pdf_url: str | None = None
    court: str | None = None
    year: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class PipelineSuccess(BaseModel):
    """Successful response with answer + citations."""

    answer: str
    citations: list[CitationCard]
    request_id: str
    cache_hit: bool
    latency_ms: float

    # Telemetry fields — populated by the pipeline but excluded from the
    # HTTP response. The route's QueryLogWriter reads them. The frontend
    # never sees them (and per AGENT-frontend.md its Zod schema doesn't
    # name them, which is fine because the response simply omits them).
    # `None` is correct for cache hits (we don't re-tokenize) and for
    # responses where the Gemini SDK didn't report usage_metadata.
    prompt_tokens: int | None = Field(default=None, exclude=True)
    output_tokens: int | None = Field(default=None, exclude=True)


class PipelineOutOfScope(BaseModel):
    """The query was rejected as out-of-scope.

    Has its own model rather than reusing PipelineSuccess because the
    frontend renders this with a different panel (suggestions instead of
    an answer + citations). Carries `error_code` for the frontend's
    discriminated union (AGENT-frontend.md §12.2).
    """

    error_code: Literal["out_of_scope"] = "out_of_scope"
    suggestions: list[str]
    request_id: str
    latency_ms: float


PipelineResponse = PipelineSuccess | PipelineOutOfScope


# ---------------------------------------------------------------------------
# Citation card construction.
# ---------------------------------------------------------------------------
def _build_citation_card(index: int, chunk: RetrievedChunk) -> CitationCard:
    """Render a retrieved chunk as the frontend-shaped CitationCard.

    Acts and judgments have different metadata shapes; we normalize both
    here so the frontend doesn't have to branch on source_type when
    rendering basic fields. Source-specific fields (court, year for
    judgments; section_heading for acts) stay in `metadata`.
    """
    meta = chunk.metadata
    source_type = meta.get("source_type", "act")

    if source_type == "act":
        short_name = meta.get("short_name") or meta.get("act_id", "")
        section_num = meta.get("section_number", "")
        citation = f"{short_name} §{section_num}".strip()
        source_url = meta.get("source_url")
        court = None
        year = None
        pdf_url = None
    else:
        # judgment
        citation = meta.get("citation") or meta.get("case_name", "")
        source_url = meta.get("indian_kanoon_url") or meta.get("source_url")
        court = meta.get("court")
        year = meta.get("year")
        # PDF link: ingestion stamps pdf_filename onto judgments; the HTTP
        # layer will eventually serve these from a /static/ route. For
        # now we just surface the filename so the frontend has something
        # to link to.
        pdf_url = meta.get("pdf_filename")

    # Excerpt: first ~300 chars of the chunk text. The frontend's
    # citation card has expandable detail, so we don't need the full body.
    excerpt = chunk.text[:300] + ("…" if len(chunk.text) > 300 else "")

    return CitationCard(
        index=index,
        source_type=source_type if source_type in ("act", "judgment") else "act",
        citation=citation,
        excerpt=excerpt,
        source_url=source_url,
        pdf_url=pdf_url,
        court=court,
        year=year,
        metadata=meta,
    )


# ---------------------------------------------------------------------------
# Pipeline.
# ---------------------------------------------------------------------------
class Pipeline:
    """Top-level orchestrator wiring cache + retrieval + generation."""

    def __init__(
        self,
        retriever: Retriever,
        generator: Generator,
        exact_cache: ExactAnswerCache,
        corpus_version: str,
    ) -> None:
        self._retriever = retriever
        self._generator = generator
        self._cache = exact_cache
        self._corpus_version = corpus_version

    async def answer(
        self, query: str, *, request_id: str | None = None,
    ) -> PipelineResponse:
        # If the HTTP layer is calling us, it has already minted a request_id
        # in middleware and stashed it on request.state. Re-using that id
        # keeps logs, response headers, and response bodies aligned.
        # For the CLI entry point (no HTTP context), we generate our own.
        if request_id is None:
            request_id = uuid.uuid4().hex
        t_start = time.perf_counter()

        # 1. Exact-cache lookup.
        cached = await self._cache.get(
            query, current_corpus_version=self._corpus_version,
        )
        if cached is not None:
            latency_ms = (time.perf_counter() - t_start) * 1000
            logger.info(
                "pipeline: cache hit (request_id=%s, latency_ms=%.1f)",
                request_id, latency_ms,
            )
            return self._cached_to_response(cached, request_id, latency_ms)

        # 2. Hybrid retrieval + scope check.
        outcome: RetrievalOutcome = await self._retriever.retrieve(query)

        if isinstance(outcome, RetrievalOutOfScope):
            latency_ms = (time.perf_counter() - t_start) * 1000
            logger.info(
                "pipeline: out-of-scope (request_id=%s, top_sim=%.3f, latency_ms=%.1f)",
                request_id, outcome.top_vector_similarity, latency_ms,
            )
            return PipelineOutOfScope(
                suggestions=list(outcome.suggestions),
                request_id=request_id,
                latency_ms=latency_ms,
            )

        assert isinstance(outcome, RetrievalSuccess)

        # 3. Generation.
        verified = await self._generator.generate(query, outcome.chunks)

        # 4. Build response envelope.
        citations = [
            _build_citation_card(i + 1, chunk)
            for i, chunk in enumerate(verified.used_chunks)
        ]
        latency_ms = (time.perf_counter() - t_start) * 1000
        response = PipelineSuccess(
            answer=verified.answer_text,
            citations=citations,
            request_id=request_id,
            cache_hit=False,
            latency_ms=latency_ms,
            prompt_tokens=verified.prompt_tokens,
            output_tokens=verified.output_tokens,
        )

        # 5. Cache.
        await self._cache.put(
            query,
            CachedAnswer(
                answer_text=verified.answer_text,
                used_chunk_ids=[c.chunk_id for c in verified.used_chunks],
                used_chunk_metadata=[c.metadata for c in verified.used_chunks],
                used_chunk_texts=[c.text for c in verified.used_chunks],
                corpus_version=self._corpus_version,
            ),
        )

        logger.info(
            "pipeline: success (request_id=%s, citations=%d, latency_ms=%.1f)",
            request_id, len(citations), latency_ms,
        )
        return response

    def _cached_to_response(
        self,
        cached: CachedAnswer,
        request_id: str,
        latency_ms: float,
    ) -> PipelineSuccess:
        """Rebuild a `PipelineSuccess` from a cache entry."""
        citations: list[CitationCard] = []
        for i, (cid, meta, text) in enumerate(
            zip(
                cached.used_chunk_ids,
                cached.used_chunk_metadata,
                cached.used_chunk_texts,
            ),
            start=1,
        ):
            citations.append(
                _build_citation_card(
                    i,
                    RetrievedChunk(
                        chunk_id=cid,
                        text=text,
                        score=0.0,  # not preserved through cache
                        source="hybrid",
                        metadata=meta,
                    ),
                )
            )
        return PipelineSuccess(
            answer=cached.answer_text,
            citations=citations,
            request_id=request_id,
            cache_hit=True,
            latency_ms=latency_ms,
        )


# ---------------------------------------------------------------------------
# CLI entry point.
# ---------------------------------------------------------------------------
def _configure_cli_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


async def _run_cli(query: str) -> int:
    # Lazy import to keep top-of-module imports cycle-free.
    from backend.app.container import Container

    container = Container()
    pipeline = container.pipeline()
    response = await pipeline.answer(query)
    print(json.dumps(response.model_dump(), indent=2, default=str))
    return 0


def main() -> int:
    _configure_cli_logging()
    if len(sys.argv) < 2:
        print("Usage: python -m backend.app.rag.pipeline <query>", file=sys.stderr)
        return 2
    query = " ".join(sys.argv[1:])

    import asyncio
    return asyncio.run(_run_cli(query))


if __name__ == "__main__":
    sys.exit(main())