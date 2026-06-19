"""Admin endpoints — the data API behind the `/admin` dashboard route.

Three endpoints, all under `/api/admin/`, all gated by the
`x-admin-password` header:

  - GET /api/admin/summary           — aggregate stats + per-day series
  - GET /api/admin/top-questions     — most-asked questions
  - GET /api/admin/recent-queries    — paginated recent query log

Each endpoint:
  1. Validates the admin password (raises AdminAuthFailed -> 401)
  2. Resolves the date window (query params or default to last 7 days)
  3. Calls the QueryLogAggregator to compute the metric
  4. Maps the dataclass result to a Pydantic response model

The aggregator does no caching, so every request walks the relevant
log partitions fresh. For our scale this is fine; if it becomes hot,
add a 60-second memoize at this layer (not inside the aggregator).
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Annotated

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, Header, Query, Request

from backend.app.admin.aggregations import (
    DEFAULT_WINDOW_DAYS,
    MAX_WINDOW_DAYS,
    DateRange,
    QueryLogAggregator,
)
from backend.app.admin.auth import AdminAuth
from backend.app.container import Container
from backend.app.errors import InvalidQuery
from backend.app.schemas.admin import (
    DailyStatsResponse,
    RecentQueriesResponse,
    RecentQueryEntry,
    SummaryResponse,
    TopQuestionEntry,
    TopQuestionsResponse,
)


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])


# ---------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------

def _parse_window(
    start: str | None, end: str | None, days: int | None,
) -> DateRange:
    """Resolve the date window from query params.

    Precedence:
      1. If both `start` and `end` are given → explicit range
      2. Else if `days` is given → trailing N days
      3. Else → trailing DEFAULT_WINDOW_DAYS

    Caps at MAX_WINDOW_DAYS to bound the document-read cost.
    """
    if start is not None and end is not None:
        try:
            start_d = dt.date.fromisoformat(start)
            end_d = dt.date.fromisoformat(end)
        except ValueError as e:
            raise InvalidQuery(f"Bad date in window: {e}") from e
        if end_d < start_d:
            raise InvalidQuery("end_date must be >= start_date")
        span = (end_d - start_d).days + 1
        if span > MAX_WINDOW_DAYS:
            raise InvalidQuery(
                f"Window too wide ({span} days); max is {MAX_WINDOW_DAYS}"
            )
        return DateRange(start=start_d, end=end_d)

    effective_days = days if days is not None else DEFAULT_WINDOW_DAYS
    if effective_days < 1:
        raise InvalidQuery("days must be >= 1")
    if effective_days > MAX_WINDOW_DAYS:
        raise InvalidQuery(
            f"days too large ({effective_days}); max is {MAX_WINDOW_DAYS}"
        )
    return DateRange.trailing(effective_days)


def _verify_admin(
    admin_auth: AdminAuth,
    provided_password: str | None,
) -> None:
    """One-line shim — keeps the call site readable in each endpoint."""
    admin_auth.verify(provided_password)


# ---------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------

@router.get("/summary", response_model=SummaryResponse)
@inject
async def admin_summary(
    request: Request,
    start_date: Annotated[str | None, Query()] = None,
    end_date: Annotated[str | None, Query()] = None,
    days: Annotated[int | None, Query(ge=1, le=MAX_WINDOW_DAYS)] = None,
    x_admin_password: Annotated[str | None, Header(alias="x-admin-password")] = None,
    admin_auth: AdminAuth = Depends(Provide[Container.admin_auth]),
    aggregator: QueryLogAggregator = Depends(Provide[Container.query_log_aggregator]),
) -> SummaryResponse:
    _verify_admin(admin_auth, x_admin_password)
    window = _parse_window(start_date, end_date, days)
    request_id = getattr(request.state, "request_id", "no-request-id")
    logger.info(
        "admin/summary: request_id=%s window=%s..%s",
        request_id, window.start, window.end,
    )

    stats = await aggregator.summary(window)
    return SummaryResponse(
        window_start=stats.window_start,
        window_end=stats.window_end,
        total_queries=stats.total_queries,
        total_successes=stats.total_successes,
        total_rejections=stats.total_rejections,
        total_cache_hits=stats.total_cache_hits,
        rejection_rate=stats.rejection_rate,
        cache_hit_rate=stats.cache_hit_rate,
        p50_latency_ms=stats.p50_latency_ms,
        p95_latency_ms=stats.p95_latency_ms,
        total_estimated_cost_usd=stats.total_estimated_cost_usd,
        daily=[
            DailyStatsResponse(
                date=d.date,
                total=d.total,
                successes=d.successes,
                rejections=d.rejections,
                cache_hits=d.cache_hits,
                avg_latency_ms=d.avg_latency_ms,
                estimated_cost_usd=d.estimated_cost_usd,
            )
            for d in stats.daily
        ],
    )


@router.get("/top-questions", response_model=TopQuestionsResponse)
@inject
async def admin_top_questions(
    request: Request,
    start_date: Annotated[str | None, Query()] = None,
    end_date: Annotated[str | None, Query()] = None,
    days: Annotated[int | None, Query(ge=1, le=MAX_WINDOW_DAYS)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 10,
    x_admin_password: Annotated[str | None, Header(alias="x-admin-password")] = None,
    admin_auth: AdminAuth = Depends(Provide[Container.admin_auth]),
    aggregator: QueryLogAggregator = Depends(Provide[Container.query_log_aggregator]),
) -> TopQuestionsResponse:
    _verify_admin(admin_auth, x_admin_password)
    window = _parse_window(start_date, end_date, days)
    request_id = getattr(request.state, "request_id", "no-request-id")
    logger.info(
        "admin/top-questions: request_id=%s window=%s..%s limit=%d",
        request_id, window.start, window.end, limit,
    )

    items = await aggregator.top_questions(window, limit=limit)
    return TopQuestionsResponse(
        window_start=window.start.strftime("%Y-%m-%d"),
        window_end=window.end.strftime("%Y-%m-%d"),
        items=[
            TopQuestionEntry(question=q, count=c) for q, c in items
        ],
    )


@router.get("/recent-queries", response_model=RecentQueriesResponse)
@inject
async def admin_recent_queries(
    request: Request,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    x_admin_password: Annotated[str | None, Header(alias="x-admin-password")] = None,
    admin_auth: AdminAuth = Depends(Provide[Container.admin_auth]),
    aggregator: QueryLogAggregator = Depends(Provide[Container.query_log_aggregator]),
) -> RecentQueriesResponse:
    _verify_admin(admin_auth, x_admin_password)
    request_id = getattr(request.state, "request_id", "no-request-id")
    logger.info(
        "admin/recent-queries: request_id=%s limit=%d offset=%d",
        request_id, limit, offset,
    )

    items, total = await aggregator.recent_queries(limit=limit, offset=offset)

    return RecentQueriesResponse(
        items=[
            RecentQueryEntry(
                request_id=doc.get("request_id", ""),
                timestamp_utc=doc.get("timestamp_utc", ""),
                hashed_ip_short=(doc.get("hashed_ip") or "")[:12],
                question=doc.get("question", ""),
                rejected=bool(doc.get("rejected")),
                cache_hit=bool(doc.get("cache_hit")),
                latency_ms=float(doc.get("latency_ms") or 0.0),
                citation_count=int(doc.get("citation_count") or 0),
                estimated_cost_usd=float(doc.get("estimated_cost_usd") or 0.0),
            )
            for doc in items
        ],
        total=total,
        limit=limit,
        offset=offset,
    )