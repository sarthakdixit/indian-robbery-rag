"""POST /api/query — the main RAG endpoint.

Wraps the Chunk 3.4 Pipeline in FastAPI. The route is responsible for:
  - Validating the request body (Pydantic via `QueryRequest`)
  - Resolving the Pipeline from the DI container (`@inject` decorator)
  - Translating adapter-layer Gemini errors into typed `AppError`s
  - Returning the typed response model

NOT in this chunk:
  - Turnstile verification (4.3) — a no-op stub for now
  - Rate limiting (4.2) — counters not yet wired
  - Query logging (4.4) — telemetry not yet wired

Per AGENT.md §17.1 the `@inject` decorator MUST be applied after the
FastAPI route decorator (route decorator outer, inject inner).
"""

from __future__ import annotations

import logging
from typing import Annotated, Union

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Body, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from backend.app.clients.gemini import (
    GeminiEmbeddingsError,
    GeminiGenerationError,
    GeminiQuotaExhausted,
)
from backend.app.container import Container
from backend.app.errors import LLMUnavailable
from backend.app.protocols.telemetry import TelemetryEmitter
from backend.app.protocols.turnstile import TurnstileVerifier
from backend.app.rag.pipeline import Pipeline, PipelineOutOfScope, PipelineSuccess
from backend.app.security.circuit_breaker import CircuitBreaker
from backend.app.security.rate_limit import GlobalCap, RateLimiter
from backend.app.telemetry.query_log import QueryLogWriter


logger = logging.getLogger(__name__)

router = APIRouter()


class QueryRequest(BaseModel):
    """Inbound query request body.

    Matches AGENT-frontend.md's `SubmitQueryInput` Zod schema verbatim
    (case-sensitive). The frontend's typed client serializes this same
    shape via the OpenAPI-generated client.

    `turnstile_token` is verified server-side via the TurnstileVerifier
    adapter. In local mode (AlwaysValid), any non-empty string passes.
    In cloud mode (Cloudflare), the token must be a valid live token
    from Cloudflare's challenge widget.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    question: str = Field(min_length=3, max_length=1000)
    turnstile_token: str = Field(min_length=1)


# Discriminated-union response: either a successful answer or an
# out-of-scope rejection. Both are 200 OK from FastAPI's perspective;
# the frontend's typed switch dispatches on the shape. Errors (rate
# limit, quota, etc.) come back as HTTP non-200 with an `error_code`
# envelope handled in `main.py`'s exception handler.
QueryResponse = Union[PipelineSuccess, PipelineOutOfScope]


@router.post("/api/query", response_model=QueryResponse, tags=["query"])
@inject
async def query_endpoint(
    request: Request,
    body: Annotated[QueryRequest, Body()],
    pipeline: Pipeline = Depends(Provide[Container.pipeline]),
    turnstile: TurnstileVerifier = Depends(Provide[Container.turnstile_verifier]),
    rate_limiter: RateLimiter = Depends(Provide[Container.rate_limiter]),
    global_cap: GlobalCap = Depends(Provide[Container.global_cap]),
    circuit_breaker: CircuitBreaker = Depends(Provide[Container.circuit_breaker]),
    query_log_writer: QueryLogWriter = Depends(Provide[Container.query_log_writer]),
    telemetry: TelemetryEmitter = Depends(Provide[Container.telemetry]),
) -> QueryResponse:
    request_id = getattr(request.state, "request_id", "no-request-id")
    hashed_ip = getattr(request.state, "hashed_ip", "no-hash")
    raw_client_ip = getattr(request.state, "raw_client_ip", None)

    logger.info(
        "query received: request_id=%s hashed_ip=%s question_len=%d",
        request_id, hashed_ip, len(body.question),
    )

    # --- Pre-flight policy checks --------------------------------------
    # Order is deliberate:
    #   1. Turnstile — filter bots first; per AGENT.md §2.1 this is the
    #      hard outer perimeter that the rest of the policy stack
    #      assumes has fired.
    #   2. Rate limit — cheapest after Turnstile (single DB read).
    #   3. Global cap — second DB read.
    #   4. Circuit breaker — in-memory, but conceptually the last gate
    #      because it protects the LLM specifically.
    await turnstile.verify(body.turnstile_token, raw_client_ip)
    await rate_limiter.check(hashed_ip)        # raises RateLimitExceeded (429)
    await global_cap.check()                    # raises GlobalCapReached (503)
    circuit_breaker.check()                     # raises CircuitBreakerOpen (503)

    # --- Run pipeline --------------------------------------------------
    try:
        response = await pipeline.answer(body.question, request_id=request_id)
    except GeminiQuotaExhausted as e:
        # Daily / per-minute Gemini quota tripped. Map to 503 with a
        # friendly error_code so the frontend can render the "we're
        # temporarily over capacity" panel.
        logger.warning(
            "gemini quota exhausted: request_id=%s err=%s", request_id, e,
        )
        raise LLMUnavailable("Gemini quota exhausted") from e
    except (GeminiEmbeddingsError, GeminiGenerationError) as e:
        # Other Gemini failures — network errors, API contract changes,
        # safety filter rejections. Treat as unavailable for now; if we
        # need finer granularity, split into specific AppError subclasses
        # in a later chunk.
        logger.error(
            "gemini failure: request_id=%s err=%s", request_id, e,
        )
        raise LLMUnavailable("LLM call failed") from e

    # --- Post-flight counter updates -----------------------------------
    # Global cap counts EVERY served response (success or OOS) per
    # design.md §4 AP-3. Per-IP rate limit counts only successes per
    # design.md FR-3 ("rejected queries do not count toward rate limits").
    # Circuit breaker counts only actual LLM calls (cache hits don't
    # consume Gemini quota).
    #
    # We swallow counter-write errors with WARNING-level logs rather
    # than failing the response — the user already got their answer;
    # losing a counter increment is preferable to a 500.
    try:
        await global_cap.increment()
    except Exception as e:
        logger.warning("global_cap.increment failed: request_id=%s err=%s",
                       request_id, e)

    if isinstance(response, PipelineSuccess):
        try:
            await rate_limiter.increment(hashed_ip)
        except Exception as e:
            logger.warning("rate_limiter.increment failed: request_id=%s err=%s",
                           request_id, e)

        if not response.cache_hit:
            try:
                circuit_breaker.record_llm_call()
            except Exception as e:
                logger.warning("circuit_breaker.record failed: request_id=%s err=%s",
                               request_id, e)

    # --- Telemetry ----------------------------------------------------
    # Two writes: a durable query_log document for the admin dashboard
    # (90-day TTL) and a transient structured event for operator
    # observability (stdout locally, App Insights in cloud). Both are
    # best-effort; failures log a warning and don't affect the response.
    try:
        await query_log_writer.write(
            request_id=request_id,
            hashed_ip=hashed_ip,
            question=body.question,
            response=response,
        )
    except Exception as e:
        logger.warning("query_log.write failed: request_id=%s err=%s",
                       request_id, e)

    try:
        is_success = isinstance(response, PipelineSuccess)
        telemetry.emit_event(
            "query_completed",
            {
                "request_id": request_id,
                "hashed_ip": hashed_ip,
                "rejected": not is_success,
                "cache_hit": is_success and response.cache_hit,
                "latency_ms": response.latency_ms,
                "citation_count": len(response.citations) if is_success else 0,
                "prompt_tokens": response.prompt_tokens if is_success else None,
                "output_tokens": response.output_tokens if is_success else None,
            },
        )
    except Exception as e:
        logger.warning("telemetry.emit_event failed: request_id=%s err=%s",
                       request_id, e)

    return response