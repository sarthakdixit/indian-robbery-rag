"""Process-local circuit breaker for the LLM.

design.md AP-4 calls for a "Python backend tracks daily Gemini call
count, refuses LLM calls past threshold." This is proactive quota
management rather than a traditional failure-based circuit breaker —
the name in design.md is slightly off, but the intent is clear:
self-throttle BEFORE Gemini's free-tier daily limit returns 429s.

State is intentionally process-local (not shared via Cosmos) per
AGENT.md §16.6 reasoning: a counter that resets on container restart
is acceptable for portfolio scale, and avoids a Cosmos write on every
LLM call. If Container Apps scales to zero overnight and a fresh
container starts in the morning, the counter resets — that's fine,
because the LLM's quota also resets overnight.

The counter resets on UTC date change (lazy check on every operation),
so a single long-running container correctly forgets yesterday's count.

Cache hits do NOT count — only actual LLM invocations. The route
inspects `response.cache_hit` to decide whether to call
`record_llm_call()`.
"""

from __future__ import annotations

import datetime as dt
import logging
import threading

from backend.app.errors import AppError


logger = logging.getLogger(__name__)


class CircuitBreakerOpen(AppError):
    """The local LLM-call counter has reached the configured ceiling.

    Mapped to HTTP 503 like other LLM-unavailable conditions. The
    frontend's error panel for this looks the same as for
    LLMUnavailable from the quota-exhausted Gemini API.
    """

    http_status = 503
    error_code = "llm_unavailable"


def _today_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")


class CircuitBreaker:
    """Counts LLM calls per UTC day; raises after `daily_limit`.

    Thread-safe via a Lock — `record_llm_call` and `check` may be called
    from any worker thread under uvicorn's default config. The internal
    state is a (date, count) pair that resets when the date changes.
    """

    def __init__(self, daily_limit: int) -> None:
        self._limit = daily_limit
        self._lock = threading.Lock()
        self._current_day: str = _today_utc()
        self._calls_today: int = 0

    def _maybe_reset(self) -> None:
        # Caller holds the lock.
        today = _today_utc()
        if today != self._current_day:
            logger.info(
                "circuit_breaker: day rollover %s -> %s, reset counter (was %d)",
                self._current_day, today, self._calls_today,
            )
            self._current_day = today
            self._calls_today = 0

    def check(self) -> None:
        """Raise CircuitBreakerOpen if the daily LLM cap is reached.

        Called BEFORE the pipeline runs. If the cap is hit, the request
        skips the LLM entirely and returns 503.
        """
        with self._lock:
            self._maybe_reset()
            if self._calls_today >= self._limit:
                logger.warning(
                    "circuit_breaker: open (%d calls today, limit %d)",
                    self._calls_today, self._limit,
                )
                raise CircuitBreakerOpen(
                    f"Local LLM call budget ({self._limit}/day) reached"
                )

    def record_llm_call(self) -> int:
        """Increment the day's counter. Returns the new value.

        Called AFTER a successful LLM call (not cache hits).
        """
        with self._lock:
            self._maybe_reset()
            self._calls_today += 1
            count = self._calls_today
        if count % 10 == 0:
            logger.info(
                "circuit_breaker: %d/%d LLM calls used today",
                count, self._limit,
            )
        return count

    def current_count(self) -> int:
        """Diagnostic accessor. Not part of any Protocol."""
        with self._lock:
            self._maybe_reset()
            return self._calls_today