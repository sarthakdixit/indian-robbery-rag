"""Request-context middleware.

Generates a UUID per request and attaches it to `request.state.request_id`
so downstream handlers can reference it in logs and responses. Also
computes the hashed IP (SHA-256 of IP + salt, per AGENT.md §10.3 and
design.md NFR-6) and stashes it on `request.state.hashed_ip`.

Why a salt: a bare SHA-256 of an IP address is still a stable, reversible
identifier for anyone running the same hash on a known IP. The salt
breaks rainbow-table lookups. The salt is configured via Settings and
should be stable across the cluster but unknown outside it.

For local development the salt has a fixed default (set in Settings).
For cloud deployment it should be set via Key Vault.

The middleware does NOT enforce any policy — it only enriches the request
context. Rate limiting, scope checking, and other policy live in
dedicated route-level dependencies (Chunk 4.2).
"""

from __future__ import annotations

import hashlib
import uuid
from typing import Awaitable, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware


def hash_client_ip(raw_ip: str, salt: str) -> str:
    """Return a hex SHA-256 of the IP + salt. Stable per (IP, salt) pair."""
    h = hashlib.sha256()
    h.update(salt.encode("utf-8"))
    h.update(b":")
    h.update(raw_ip.encode("utf-8"))
    return h.hexdigest()


def _extract_client_ip(request: Request) -> str:
    """Best-effort client IP from a FastAPI Request.

    Behind Azure Static Web Apps' backend linking and Container Apps'
    ingress, the real client IP arrives in `x-forwarded-for`. The header
    is a comma-separated chain; the leftmost entry is the original
    client. We trust this header because the only thing in front of our
    backend in production is Azure's own infrastructure (which sets it).

    For local dev, fall back to `request.client.host`, which is the
    direct TCP peer (typically 127.0.0.1).
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        first = forwarded.split(",", 1)[0].strip()
        if first:
            return first
    if request.client is not None:
        return request.client.host
    return "unknown"


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Enriches `request.state` with `request_id` and `hashed_ip`.

    Uses Starlette's `BaseHTTPMiddleware` rather than raw ASGI because:
      - The state-mutation pattern is idiomatic and well-documented
      - We don't need contextvars propagation across middleware layers
        (the warnings in the Starlette docs about BaseHTTPMiddleware
        relate to contextvars, not request.state mutation)
      - It is forward-compatible with FastAPI's typed `Request` object

    The `salt` is read at construction time rather than per-request
    because it doesn't change at runtime.
    """

    def __init__(self, app, salt: str) -> None:
        super().__init__(app)
        self._salt = salt

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        raw_ip = _extract_client_ip(request)
        request.state.request_id = uuid.uuid4().hex
        request.state.raw_client_ip = raw_ip
        request.state.hashed_ip = hash_client_ip(raw_ip, self._salt)
        response = await call_next(request)
        # Echo the request_id back in a response header — useful for
        # client-side debugging and for matching support tickets to logs.
        response.headers["x-request-id"] = request.state.request_id
        return response