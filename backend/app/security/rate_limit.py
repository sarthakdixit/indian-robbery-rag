"""Per-IP rate limit and global daily cap.

Both policies use date-bucket counters in the DocumentStore. The key
difference is the partition strategy:

  - **Per-IP rate limit** (5 per UTC day per hashed IP): key on
    `rate:<hashed_ip>` partition with `<YYYY-MM-DD>` doc_id. Out-of-scope
    queries do NOT count (design.md FR-3); only PipelineSuccess
    increments. TTL is 48 hours so yesterday's document expires after
    today.

  - **Global cap** (default 200 per UTC day across all IPs): key on
    `global` partition with `<YYYY-MM-DD>` doc_id. Counts EVERY served
    response, success or OOS, per design.md §4 AP-3. No TTL — the
    historical counters are kept for the admin dashboard.

Both expose `check()` (reads counter, raises if over) and `increment()`
(atomic +1). The route calls `check()` before running the pipeline and
`increment()` after, conditionally on the response type.

Race condition: between `check()` and `increment()`, the same client
could fire N parallel requests, all see counter=4, and all increment to
5/6/7/.../4+N. For our threshold of 5 and the demo's expected traffic,
this is theoretical. The proper fix (atomic compare-and-swap on
increment) costs more code than it saves; skipped.

Deviation from design.md FR-5: design.md says "5 queries per IP per
24-hour ROLLING window". We implement "5 per UTC day" (resetting at
midnight). The Cosmos schema in §9 ("date bucket" as doc_id) is
consistent with our interpretation. README will note this.
"""

from __future__ import annotations

import datetime as dt
import logging

from backend.app.errors import AppError
from backend.app.protocols.document_store import DocumentStore


logger = logging.getLogger(__name__)


_COUNTER_FIELD = "count"
_PER_IP_PARTITION_PREFIX = "rate:"
_GLOBAL_PARTITION = "global"

# 48 hours so yesterday's per-IP doc auto-expires after today rolls in.
# Global counters have no TTL — the admin dashboard wants history.
_PER_IP_TTL_SECONDS: int = 48 * 60 * 60


class RateLimitExceeded(AppError):
    """The per-IP rate limit has been hit for this UTC day."""

    http_status = 429
    error_code = "rate_limit_exceeded"


class GlobalCapReached(AppError):
    """The global daily cap has been hit for this UTC day.

    HTTP 503 (not 429) because this is a service-side capacity issue,
    not a per-client issue. The frontend renders this differently from
    a rate-limit error (`demo_at_capacity` panel rather than countdown).
    """

    http_status = 503
    error_code = "demo_at_capacity"


def _utc_date_bucket(now: dt.datetime | None = None) -> str:
    """Return the date-bucket key for the current UTC day, YYYY-MM-DD."""
    if now is None:
        now = dt.datetime.now(dt.timezone.utc)
    return now.strftime("%Y-%m-%d")


class RateLimiter:
    """Per-IP daily request counter."""

    def __init__(
        self,
        store: DocumentStore,
        daily_limit: int,
    ) -> None:
        self._store = store
        self._limit = daily_limit

    async def check(self, hashed_ip: str) -> None:
        """Raise RateLimitExceeded if the IP has used up its quota."""
        partition = _PER_IP_PARTITION_PREFIX + hashed_ip
        bucket = _utc_date_bucket()
        doc = await self._store.get(partition, bucket)
        used = int(doc.get(_COUNTER_FIELD, 0)) if doc else 0
        if used >= self._limit:
            logger.info(
                "rate_limit: hashed_ip=%s used=%d limit=%d -> reject",
                hashed_ip, used, self._limit,
            )
            raise RateLimitExceeded(
                f"Rate limit ({self._limit}/day) reached for this IP"
            )

    async def increment(self, hashed_ip: str) -> int:
        """Increment the IP's counter. Returns the new value.

        Designed to be called AFTER a successful Pipeline response. OOS
        responses should not call this.
        """
        partition = _PER_IP_PARTITION_PREFIX + hashed_ip
        bucket = _utc_date_bucket()
        new_value = await self._store.increment_counter(
            partition_key=partition,
            doc_id=bucket,
            field=_COUNTER_FIELD,
            amount=1,
            ttl_seconds=_PER_IP_TTL_SECONDS,
        )
        return new_value


class GlobalCap:
    """Daily-total counter across all clients."""

    def __init__(self, store: DocumentStore, daily_cap: int) -> None:
        self._store = store
        self._cap = daily_cap

    async def check(self) -> None:
        """Raise GlobalCapReached if the global cap has been hit."""
        doc = await self._store.get(_GLOBAL_PARTITION, _utc_date_bucket())
        served = int(doc.get(_COUNTER_FIELD, 0)) if doc else 0
        if served >= self._cap:
            logger.warning(
                "global_cap: served=%d cap=%d -> reject",
                served, self._cap,
            )
            raise GlobalCapReached(
                f"Daily request cap ({self._cap}) reached"
            )

    async def increment(self) -> int:
        """Increment the global counter for today. No TTL.

        Called after EVERY served response (success or OOS) per
        design.md §4 AP-3.
        """
        return await self._store.increment_counter(
            partition_key=_GLOBAL_PARTITION,
            doc_id=_utc_date_bucket(),
            field=_COUNTER_FIELD,
            amount=1,
            ttl_seconds=None,
        )