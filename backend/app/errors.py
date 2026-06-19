"""HTTP-layer error types.

Per AGENT.md §9, every distinct failure mode is its own typed exception
subclass of `AppError`. A single FastAPI exception handler translates
them to HTTP responses by reading `http_status` and `error_code`.

Adapter-layer exceptions (e.g., `GeminiQuotaExhausted` from
`clients/gemini.py`) are translated at the route boundary, not by being
subclassed under `AppError` — keeping the adapter layer ignorant of HTTP
status codes preserves separation of concerns.

Chunk 4.1 ships the base class plus the minimum subclasses needed for
the routes that exist now. Subsequent chunks add:
  - 4.2: RateLimitExceeded, GlobalCapReached, CircuitBreakerOpen
  - 4.3: TurnstileVerificationFailed
  - 4.4: nothing new (telemetry doesn't fail user-visibly)
"""

from __future__ import annotations


class AppError(Exception):
    """Base for all application errors that should map to a typed HTTP
    response. Subclasses set `http_status` and `error_code` as class vars.

    The default 500 / "internal_error" pair is the fallback for any
    `AppError` subclass that forgets to override — visible in logs but
    not user-facing surprises.
    """

    http_status: int = 500
    error_code: str = "internal_error"


class LLMUnavailable(AppError):
    """The generation LLM is unavailable.

    Used for Gemini quota exhaustion (when daily/per-minute caps trip),
    other Gemini-side failures translated at the route boundary, and
    eventually the circuit-breaker-open case (Chunk 4.2). All three are
    "service-side unavailable, retry later" from the user's perspective,
    hence the shared HTTP 503.
    """

    http_status = 503
    error_code = "llm_unavailable"


class InvalidQuery(AppError):
    """The query failed pre-pipeline validation that Pydantic couldn't
    catch (e.g., a question that's a URL, an injection attempt). Mapped
    to HTTP 400 so the frontend can surface a specific error panel."""

    http_status = 400
    error_code = "invalid_query"


class TurnstileVerificationFailed(AppError):
    """The Turnstile token was rejected by Cloudflare.

    Maps to HTTP 403 because Cloudflare considers the request
    unauthorized (forged token, expired token, replayed token, etc.).
    The frontend's TurnstileFailurePanel offers a "retry" action that
    refreshes the widget and re-submits.
    """

    http_status = 403
    error_code = "turnstile_failed"


class AdminAuthFailed(AppError):
    """The `x-admin-password` header was missing or wrong.

    Maps to HTTP 401 (not 403) because semantically the client did not
    authenticate at all. 403 would imply "authenticated but not
    authorized for this resource", which doesn't apply — there's no
    notion of a non-admin authenticated user in this system.
    """

    http_status = 401
    error_code = "admin_auth_failed"