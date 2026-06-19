"""Aggregations over the query_log documents for the admin dashboard.

Reads from the DocumentStore via `list_by_partition` for each date in
the requested window, then computes the metrics design.md FR-10 asks
for: queries/day, p50/p95 latency, cost-to-date, top questions,
rejection rate, cache hit rate.

The aggregator does NOT cache anything — every admin request walks the
log documents fresh. For our scale (200/day cap * 7-day default window
= 1400 docs max per query), this is fine. If the dashboard becomes
hot, a memoization layer with a 60-second TTL would be the right fix.

Question normalization for "top questions": lowercase + collapse
whitespace. This merges "What is robbery?" and "what is robbery?" but
treats "What is robbery?" and "What is robbery under BNS?" as distinct.
Heavier normalization (stemming, semantic clustering) is out of scope
for v1; the eval set will tell us if that's worth doing.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
import statistics
from collections import Counter
from dataclasses import dataclass
from typing import Any

from backend.app.protocols.document_store import DocumentStore


logger = logging.getLogger(__name__)


# 7 days = sensible default window. Long enough for trends, short enough
# that a partial current day doesn't dominate.
DEFAULT_WINDOW_DAYS: int = 7

# Cap windows at 90 days because that's the query_log TTL — anything
# beyond is silently empty. A 90-day query is the most a caller can
# usefully ask for, and it costs ~18k document reads (still bounded).
MAX_WINDOW_DAYS: int = 90


_WHITESPACE_RE = re.compile(r"\s+")


def _normalize_question(question: str) -> str:
    """Group-by key for the top-questions aggregation.

    Lowercased and whitespace-collapsed. Doesn't remove punctuation
    (since "?" vs "" can carry meaning) and doesn't stem.
    """
    return _WHITESPACE_RE.sub(" ", question.strip().lower())


@dataclass(frozen=True)
class DateRange:
    """Inclusive [start, end] UTC date window."""

    start: dt.date
    end: dt.date

    def dates(self) -> list[dt.date]:
        """Every date in the inclusive range, in calendar order."""
        days: list[dt.date] = []
        current = self.start
        while current <= self.end:
            days.append(current)
            current = current + dt.timedelta(days=1)
        return days

    @classmethod
    def trailing(cls, days: int) -> DateRange:
        """Last N days ending today (UTC), inclusive on both ends."""
        end = dt.datetime.now(dt.timezone.utc).date()
        start = end - dt.timedelta(days=days - 1)
        return cls(start=start, end=end)


def _date_bucket_key(d: dt.date) -> str:
    return "log:" + d.strftime("%Y-%m-%d")


def _global_counter_key(d: dt.date) -> str:
    """The partition_key + doc_id pair for the global counter on date d.

    Matches the layout written by `security/rate_limit.py:GlobalCap`.
    """
    return d.strftime("%Y-%m-%d")


@dataclass(frozen=True)
class DailyStats:
    """Per-day rollup for time-series rendering on the dashboard."""

    date: str            # YYYY-MM-DD
    total: int           # all served responses (success + OOS)
    successes: int       # responses where rejected=False
    rejections: int      # responses where rejected=True
    cache_hits: int      # subset of successes where cache_hit=True
    avg_latency_ms: float | None
    estimated_cost_usd: float


@dataclass(frozen=True)
class SummaryStats:
    """Aggregate over the entire date range."""

    window_start: str
    window_end: str
    total_queries: int
    total_successes: int
    total_rejections: int
    total_cache_hits: int
    rejection_rate: float       # 0..1
    cache_hit_rate: float       # 0..1 over successes
    p50_latency_ms: float | None
    p95_latency_ms: float | None
    total_estimated_cost_usd: float
    daily: list[DailyStats]


class QueryLogAggregator:
    """Reads query_log documents from the DocumentStore and computes metrics."""

    def __init__(self, store: DocumentStore) -> None:
        self._store = store

    async def _fetch_window(self, window: DateRange) -> list[dict[str, Any]]:
        """Pull every log document across the window. UNORDERED."""
        all_docs: list[dict[str, Any]] = []
        for d in window.dates():
            docs = await self._store.list_by_partition(_date_bucket_key(d))
            all_docs.extend(docs)
        return all_docs

    async def summary(self, window: DateRange) -> SummaryStats:
        """Compute the full summary panel from a date-range window."""
        docs = await self._fetch_window(window)

        per_day_buckets: dict[str, list[dict[str, Any]]] = {}
        for doc in docs:
            day = doc.get("timestamp_utc", "")[:10] or "unknown"
            per_day_buckets.setdefault(day, []).append(doc)

        # Daily stats — one entry per calendar day in the window, even
        # for days with zero traffic (so the dashboard chart shows gaps).
        daily: list[DailyStats] = []
        for d in window.dates():
            key = d.strftime("%Y-%m-%d")
            day_docs = per_day_buckets.get(key, [])
            daily.append(_compute_daily_stats(key, day_docs))

        # Aggregate counts.
        total = len(docs)
        rejections = sum(1 for d in docs if d.get("rejected"))
        successes = total - rejections
        cache_hits = sum(
            1 for d in docs if not d.get("rejected") and d.get("cache_hit")
        )

        # Latency percentiles over successes only — OOS responses have
        # near-zero latency (no Gemini call) and would skew the
        # distribution. Frontend cares about "how slow is the LLM
        # path?" not "how fast is rejection?".
        success_latencies = [
            float(d["latency_ms"]) for d in docs
            if not d.get("rejected") and d.get("latency_ms") is not None
        ]
        p50, p95 = _percentiles(success_latencies, (50, 95))

        # Cost sums over the entire window (cache hits contribute 0, so
        # the sum is meaningful even with cached responses).
        total_cost = sum(
            float(d.get("estimated_cost_usd") or 0.0) for d in docs
        )

        rejection_rate = (rejections / total) if total else 0.0
        cache_hit_rate = (cache_hits / successes) if successes else 0.0

        return SummaryStats(
            window_start=window.start.strftime("%Y-%m-%d"),
            window_end=window.end.strftime("%Y-%m-%d"),
            total_queries=total,
            total_successes=successes,
            total_rejections=rejections,
            total_cache_hits=cache_hits,
            rejection_rate=rejection_rate,
            cache_hit_rate=cache_hit_rate,
            p50_latency_ms=p50,
            p95_latency_ms=p95,
            total_estimated_cost_usd=total_cost,
            daily=daily,
        )

    async def top_questions(
        self, window: DateRange, limit: int = 10,
    ) -> list[tuple[str, int]]:
        """Return the most-asked questions in the window.

        Returned as (representative_question, count) pairs, sorted by
        count desc. The "representative" question is the first one we
        encountered with that normalized form, since users see their
        original casing.
        """
        docs = await self._fetch_window(window)
        counter: Counter[str] = Counter()
        # Remember the first instance of each normalized question for
        # display — preserve the user's casing rather than show the
        # lowercase normalized form.
        first_seen: dict[str, str] = {}
        for d in docs:
            q = d.get("question")
            if not q:
                continue
            normalized = _normalize_question(q)
            counter[normalized] += 1
            if normalized not in first_seen:
                first_seen[normalized] = q

        return [
            (first_seen[norm], count)
            for norm, count in counter.most_common(limit)
        ]

    async def recent_queries(
        self, limit: int = 50, offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        """Most recent N log entries. Returns (items, total_available_in_window).

        Walks the last 7 days (configurable later if we need more)
        rather than scanning all 90 days — recent-queries is the most
        common admin view and reading 7 days of data is fast enough.
        """
        window = DateRange.trailing(DEFAULT_WINDOW_DAYS)
        docs = await self._fetch_window(window)
        docs.sort(key=lambda d: d.get("timestamp_utc", ""), reverse=True)
        page = docs[offset : offset + limit]
        return page, len(docs)


def _compute_daily_stats(date: str, docs: list[dict[str, Any]]) -> DailyStats:
    total = len(docs)
    rejections = sum(1 for d in docs if d.get("rejected"))
    successes = total - rejections
    cache_hits = sum(
        1 for d in docs if not d.get("rejected") and d.get("cache_hit")
    )

    success_latencies = [
        float(d["latency_ms"]) for d in docs
        if not d.get("rejected") and d.get("latency_ms") is not None
    ]
    avg_latency = (
        statistics.mean(success_latencies) if success_latencies else None
    )
    cost = sum(float(d.get("estimated_cost_usd") or 0.0) for d in docs)

    return DailyStats(
        date=date,
        total=total,
        successes=successes,
        rejections=rejections,
        cache_hits=cache_hits,
        avg_latency_ms=avg_latency,
        estimated_cost_usd=cost,
    )


def _percentiles(
    values: list[float], percentiles: tuple[int, ...],
) -> tuple[float | None, ...]:
    """Compute the requested percentiles of a list of floats.

    Returns a tuple of (None, None, ...) when the input is empty, so
    callers don't have to special-case. For very small samples (n < 20),
    percentile estimates are noisy — frontend should annotate or hide.
    """
    if not values:
        return tuple(None for _ in percentiles)
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    results: list[float] = []
    for p in percentiles:
        # Nearest-rank percentile. statistics.quantiles uses
        # exclusive interpolation which gives subtly different values;
        # the simple nearest-rank approach is unambiguous and easier
        # to explain in the README.
        idx = max(0, min(n - 1, int(round((p / 100) * (n - 1)))))
        results.append(sorted_vals[idx])
    return tuple(results)