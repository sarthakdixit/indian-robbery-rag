"""Turnstile verification protocol.

Cloudflare Turnstile is an invisible CAPTCHA. The frontend embeds the
widget, which (after a brief client-side challenge) produces a token.
The token is sent with the API request and must be verified server-side
by POSTing it to Cloudflare's siteverify endpoint along with our secret.

Per AGENT.md §2.1, this is a local/cloud adapter pair:
  - Local: AlwaysValidTurnstileVerifier (no network call)
  - Cloud: CloudflareTurnstileVerifier (real HTTPS POST)

The protocol intentionally exposes a single method that either returns
cleanly or raises. Adapters never return False; they raise the typed
TurnstileVerificationFailed for forged/expired tokens and a different
error type for transient failures (Cloudflare unreachable, etc.) so the
HTTP layer can map them to distinct status codes.

Token lifecycle quick reference (from Cloudflare docs):
  - Tokens are valid for 300 seconds (5 minutes) after generation
  - Tokens are single-use; replays return "timeout-or-duplicate"
  - The frontend (AGENT-frontend.md §20.5) refreshes tokens proactively
    at the 4-minute mark to avoid this
"""

from __future__ import annotations

from typing import Protocol


class TurnstileVerifier(Protocol):
    """Async verifier that confirms a Turnstile token is valid.

    Implementations:
      - return cleanly on success
      - raise TurnstileVerificationFailed on user-facing failures
        (forged token, expired token, replayed token)
      - raise any other typed exception (mapped to a 503 by the route)
        on infrastructure failures (Cloudflare unreachable, etc.)

    The `remote_ip` parameter is optional context Cloudflare uses for
    its own bot scoring. We pass our raw client IP (NOT the salted hash)
    because Cloudflare needs the actual IP to compute reputation. The
    hashed_ip stays internal for our own logging.
    """

    async def verify(self, token: str, remote_ip: str | None = None) -> None:
        ...