"""Per-request query log writer.

Writes one document to the DocumentStore for every served request,
following the design.md §9 schema:

    partition_key: "log:<YYYY-MM-DD>"
    doc_id: <request_id>
    body:
        request_id, timestamp_utc, hashed_ip, question,
        rejected, answer, citation_count, latency_ms, cache_hit,
        prompt_tokens, output_tokens, estimated_cost_usd
    valid_until: now + 90 days

The TTL is 90 days because that's enough for the admin dashboard to
show trends without filling SQLite/Cosmos with cruft. After 90 days,
documents are eligible for cleanup by the store's TTL mechanism.

The writer is called from `routes/query.py` after the pipeline returns
and BEFORE the HTTP response is sent — adding ~5ms of latency. We
write synchronously (await) rather than fire-and-forget because:

  - If the write fails, we still want to know (visible in logs)
  - Background tasks under uvicorn need explicit lifecycle management
  - 5ms on a 3000ms request is invisible

Failure of the write must NOT fail the response. The caller wraps the
write in try/except in the route (the same pattern as counter writes
from Chunk 4.2).

Cost calculation uses static Gemini 2.5 Flash-Lite per-token pricing.
The numbers are kept here rather than in a separate cost_tracker
module because the calculation is two multiplications — splitting it
into its own file is over-engineering. If we ever support multiple
models with different prices, we extract.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.app.protocols.document_store import DocumentStore
    from backend.app.rag.pipeline import PipelineResponse


logger = logging.getLogger(__name__)


# --- Pricing ---------------------------------------------------------
# Gemini 2.5 Flash-Lite paid-tier rates as of 2026-Q2.
# We're on the free tier so these costs are notional, but the admin
# dashboard surfaces them as "would have cost X on paid tier" — a useful
# framing for the portfolio narrative.
#   $0.10 per 1M input tokens = $1e-7 per input token
#   $0.40 per 1M output tokens = $4e-7 per output token
GEMINI_FLASH_LITE_INPUT_USD_PER_TOKEN: float = 0.10 / 1_000_000
GEMINI_FLASH_LITE_OUTPUT_USD_PER_TOKEN: float = 0.40 / 1_000_000


# --- Document store keys ---------------------------------------------
# 90 days = 7,776,000 seconds. Long enough for monthly trend graphs;
# short enough that old data doesn't accumulate forever.
_TTL_SECONDS: int = 90 * 24 * 60 * 60


def _utc_date_bucket() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")


def _utc_iso_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _compute_estimated_cost_usd(
    prompt_tokens: int | None, output_tokens: int | None,
) -> float:
    """Hypothetical cost on the paid tier. Free-tier cost is 0."""
    if prompt_tokens is None and output_tokens is None:
        return 0.0
    p = prompt_tokens or 0
    o = output_tokens or 0
    return (
        p * GEMINI_FLASH_LITE_INPUT_USD_PER_TOKEN
        + o * GEMINI_FLASH_LITE_OUTPUT_USD_PER_TOKEN
    )


class QueryLogWriter:
    """Persists one query_log document per served request."""

    def __init__(self, store: DocumentStore) -> None:
        self._store = store

    async def write(
        self,
        *,
        request_id: str,
        hashed_ip: str,
        question: str,
        response: PipelineResponse,
    ) -> None:
        """Build and upsert the query_log document.

        Errors propagate to the caller, which is responsible for
        deciding whether to log+continue (the route does) or fail.
        """
        # Local imports to avoid a circular dependency at module load
        # time (pipeline.py -> telemetry/query_log.py would be a cycle
        # if we imported at module top).
        from backend.app.rag.pipeline import PipelineOutOfScope, PipelineSuccess

        partition = "log:" + _utc_date_bucket()
        body: dict[str, object] = {
            "request_id": request_id,
            "timestamp_utc": _utc_iso_now(),
            "hashed_ip": hashed_ip,
            "question": question,
            "latency_ms": response.latency_ms,
        }

        if isinstance(response, PipelineSuccess):
            body.update({
                "rejected": False,
                "answer": response.answer,
                "citation_count": len(response.citations),
                "cache_hit": response.cache_hit,
                "prompt_tokens": response.prompt_tokens,
                "output_tokens": response.output_tokens,
                "estimated_cost_usd": _compute_estimated_cost_usd(
                    response.prompt_tokens, response.output_tokens,
                ),
            })
        elif isinstance(response, PipelineOutOfScope):
            body.update({
                "rejected": True,
                "answer": None,
                "citation_count": 0,
                "cache_hit": False,
                "prompt_tokens": None,
                "output_tokens": None,
                "estimated_cost_usd": 0.0,
            })
        else:
            # Defensive — every PipelineResponse subclass should be
            # handled above. If a new subclass is added without
            # updating this code, we want to know.
            logger.warning(
                "QueryLogWriter: unknown response type %s; writing minimal record",
                type(response).__name__,
            )
            body["rejected"] = False  # unknown; admit nothing

        await self._store.upsert(
            partition_key=partition,
            doc_id=request_id,
            body=body,
            ttl_seconds=_TTL_SECONDS,
        )