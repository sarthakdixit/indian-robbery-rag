"""Pydantic response models for the /api/admin/* endpoints.

These mirror the dataclasses in `admin/aggregations.py` but are
Pydantic so they participate in FastAPI's OpenAPI schema and the
frontend's typed client generation. Conversion from aggregator
dataclasses happens in `routes/admin.py`.

Why two parallel shapes (dataclass + Pydantic): the aggregator is
internal code that's hot in tests and shouldn't pay Pydantic's
validation cost on every numeric field. The HTTP boundary is the
right place for Pydantic. Mirror conversion is a 1-line helper.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------
# Summary endpoint
# ---------------------------------------------------------------------

class DailyStatsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date: str
    total: int
    successes: int
    rejections: int
    cache_hits: int
    avg_latency_ms: float | None
    estimated_cost_usd: float


class SummaryResponse(BaseModel):
    """Aggregate dashboard panel — counts, rates, latency, cost, per-day series."""

    model_config = ConfigDict(extra="forbid")

    window_start: str = Field(description="UTC date, inclusive lower bound")
    window_end: str = Field(description="UTC date, inclusive upper bound")
    total_queries: int
    total_successes: int
    total_rejections: int
    total_cache_hits: int
    rejection_rate: float = Field(ge=0.0, le=1.0)
    cache_hit_rate: float = Field(ge=0.0, le=1.0)
    p50_latency_ms: float | None
    p95_latency_ms: float | None
    total_estimated_cost_usd: float = Field(ge=0.0)
    daily: list[DailyStatsResponse]


# ---------------------------------------------------------------------
# Top-questions endpoint
# ---------------------------------------------------------------------

class TopQuestionEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str
    count: int = Field(ge=1)


class TopQuestionsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    window_start: str
    window_end: str
    items: list[TopQuestionEntry]


# ---------------------------------------------------------------------
# Recent queries endpoint
# ---------------------------------------------------------------------

class RecentQueryEntry(BaseModel):
    """A single row in the "recent queries" table.

    Mirrors the query_log document body shape from `telemetry/query_log.py`
    but with `hashed_ip` truncated to 12 chars for display brevity.
    Full hash stays in the underlying document.
    """

    model_config = ConfigDict(extra="forbid")

    request_id: str
    timestamp_utc: str
    hashed_ip_short: str  # first 12 chars of the full SHA-256 hex
    question: str
    rejected: bool
    cache_hit: bool
    latency_ms: float
    citation_count: int = 0
    estimated_cost_usd: float = 0.0


class RecentQueriesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[RecentQueryEntry]
    total: int = Field(description="Total available in the lookup window (not just this page)")
    limit: int
    offset: int