"""Turnstile verifier adapters.

Two implementations of the `TurnstileVerifier` protocol:

  - `AlwaysValidTurnstileVerifier`: accepts any non-empty token without
    a network call. Used in local development and unit tests. The
    constructor logs a WARNING on creation so a misdeployment to a
    public URL with environment=local is loud about it.

  - `CloudflareTurnstileVerifier`: POSTs to Cloudflare's siteverify API.
    Raises `TurnstileVerificationFailed` for verifications that
    Cloudflare rejects (forged/expired/replayed tokens). Raises
    `TurnstileServiceUnavailable` for transient infrastructure
    failures (network errors, 5xx from Cloudflare). The route layer
    maps the latter to HTTP 503.

The Cloudflare adapter shares a single `httpx.AsyncClient` across calls
for connection pooling. It is constructed once by the DI container as a
Singleton and reused for the process lifetime.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import httpx

from backend.app.errors import LLMUnavailable, TurnstileVerificationFailed

if TYPE_CHECKING:
    from backend.app.config import Settings


logger = logging.getLogger(__name__)


_CLOUDFLARE_SITEVERIFY_URL: str = (
    "https://challenges.cloudflare.com/turnstile/v0/siteverify"
)
# Cloudflare's API is usually <100ms; 5s is generous, avoids hanging the
# request indefinitely on a network blip. Fail-closed semantics: if we
# time out, the request is rejected.
_VERIFY_TIMEOUT_SECONDS: float = 5.0


class AlwaysValidTurnstileVerifier:
    """Local-mode verifier. Accepts any non-empty token.

    The constructor emits a WARNING so the operator can spot a wrong
    environment setting (e.g., `environment=local` in a cloud deploy).
    """

    def __init__(self) -> None:
        logger.warning(
            "AlwaysValidTurnstileVerifier in use — Turnstile is NOT being "
            "verified. This is correct for local dev only. Production should "
            "set environment=cloud so CloudflareTurnstileVerifier is used."
        )

    async def verify(self, token: str, remote_ip: str | None = None) -> None:
        if not token or not token.strip():
            # The route's Pydantic schema enforces min_length=1 already,
            # so this should be unreachable. Defensive guard.
            raise TurnstileVerificationFailed("empty turnstile token")
        # No further checks — local dev passes through.


class CloudflareTurnstileVerifier:
    """Cloud-mode verifier. Calls Cloudflare's siteverify endpoint.

    The adapter:
      - Posts `secret`, `response` (= token), and optional `remoteip` as
        form-urlencoded data (Cloudflare accepts both form and JSON; we
        use form since it's the most-documented path)
      - Parses the JSON response
      - Raises `TurnstileVerificationFailed` if Cloudflare says
        `success: false`, with the `error-codes` carried in the message
      - Raises `LLMUnavailable` (HTTP 503) on network errors or 5xx
        responses from Cloudflare, so the operator can distinguish
        infrastructure issues from forged tokens in the logs

    Cloudflare offers test secret keys for local exercise of this
    adapter without a real account:
      - `1x0000000000000000000000000000000AA` always passes
      - `2x0000000000000000000000000000000AA` always fails
      - `3x0000000000000000000000000000000AA` always "already-spent"
    """

    def __init__(self, settings: Settings) -> None:
        self._secret = settings.turnstile_secret_key.get_secret_value()
        # One client for the process lifetime; httpx pools connections
        # internally. `timeout` here is the per-call default; verify()
        # overrides it for clarity.
        self._client = httpx.AsyncClient(timeout=_VERIFY_TIMEOUT_SECONDS)

    async def verify(self, token: str, remote_ip: str | None = None) -> None:
        if not token or not token.strip():
            raise TurnstileVerificationFailed("empty turnstile token")

        payload: dict[str, str] = {"secret": self._secret, "response": token}
        if remote_ip:
            payload["remoteip"] = remote_ip

        try:
            response = await self._client.post(
                _CLOUDFLARE_SITEVERIFY_URL,
                data=payload,
                timeout=_VERIFY_TIMEOUT_SECONDS,
            )
        except httpx.HTTPError as e:
            logger.error(
                "turnstile: HTTP error contacting Cloudflare: %s: %s",
                type(e).__name__, e,
            )
            # Fail closed: better to reject one user than let bots in
            # during a Cloudflare incident. Maps to HTTP 503 at the
            # route handler — same panel as Gemini quota.
            raise LLMUnavailable("Turnstile verification service unreachable") from e

        if response.status_code >= 500:
            logger.error(
                "turnstile: Cloudflare returned %d: %s",
                response.status_code, response.text[:200],
            )
            raise LLMUnavailable(
                f"Turnstile verification service returned {response.status_code}"
            )

        try:
            outcome: dict[str, Any] = response.json()
        except ValueError as e:
            logger.error(
                "turnstile: non-JSON response from Cloudflare: %s",
                response.text[:200],
            )
            raise LLMUnavailable("Turnstile verification returned non-JSON") from e

        if not outcome.get("success"):
            # error-codes is a list per Cloudflare's API
            codes = outcome.get("error-codes", [])
            logger.info("turnstile: rejected token, codes=%s", codes)
            raise TurnstileVerificationFailed(
                f"Token rejected by Cloudflare: {codes}"
            )

        # Success — no return value needed; caller continues normally.
        logger.debug("turnstile: token accepted (hostname=%s)",
                     outcome.get("hostname"))

    async def aclose(self) -> None:
        """Release the httpx client. Called by container shutdown if wired."""
        await self._client.aclose()