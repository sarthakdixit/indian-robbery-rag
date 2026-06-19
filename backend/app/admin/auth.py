"""Admin password verification.

Intentionally minimal: a single shared password compared in constant
time against an `x-admin-password` HTTP header. NOT real authentication.

The threat model:
  - The dashboard URL gets shared accidentally (e.g., in a screenshot
    that leaks the GET URL). Without a password gate, that exposes the
    query log and metrics to anyone who clicks.
  - Drive-by scraping or scanning hits `/api/admin/*`. The 401 wall
    deters automated scrapers.

What this does NOT defend against:
  - A determined attacker. The password is one shared secret with no
    rotation, no per-user tracking, no rate limiting on guessing.
  - Anyone who can read environment variables or Container Apps secrets.
  - The user accidentally copying the password into a screenshot.

For a portfolio demo this is acceptable; design.md FR-10 explicitly
asks for "password-protected" not "authenticated", and the README
documents the trade-off. Real auth (OAuth, session tokens, etc.) is
out of scope for v1.
"""

from __future__ import annotations

import hmac
import logging

from fastapi import Header

from backend.app.config import Settings
from backend.app.errors import AdminAuthFailed


logger = logging.getLogger(__name__)


_ADMIN_PASSWORD_HEADER: str = "x-admin-password"


class AdminAuth:
    """Constant-time admin password check.

    Constructed as a Singleton with the configured password. The route
    layer's dependency calls `verify(provided)` on every request.
    """

    def __init__(self, settings: Settings) -> None:
        # SecretStr → str at construction time, kept in the instance.
        # The encoded bytes are used for `hmac.compare_digest` to avoid
        # timing attacks. A constant-time compare matters even at this
        # threat model because an attacker who can measure tens of
        # microseconds reliably (rare but possible on a LAN) could
        # otherwise extract the password byte by byte.
        self._expected_bytes = (
            settings.admin_password.get_secret_value().encode("utf-8")
        )

    def verify(self, provided: str | None) -> None:
        """Raise AdminAuthFailed if `provided` doesn't match the configured password.

        Passes silently on success — typical FastAPI dependency pattern.
        """
        if provided is None:
            logger.info("admin auth: no %s header provided", _ADMIN_PASSWORD_HEADER)
            raise AdminAuthFailed(
                f"Missing {_ADMIN_PASSWORD_HEADER} header"
            )
        if not hmac.compare_digest(
            provided.encode("utf-8"), self._expected_bytes,
        ):
            logger.info("admin auth: wrong password (len=%d)", len(provided))
            raise AdminAuthFailed("Invalid admin password")


# FastAPI Header dependency. Used in routes as:
#   provided = Header(None, alias="x-admin-password")
# Centralized here so the alias appears in one place.
AdminPasswordHeader = Header(default=None, alias=_ADMIN_PASSWORD_HEADER)