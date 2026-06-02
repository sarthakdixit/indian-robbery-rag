"""Telemetry adapter implementations.

Two implementations of the `TelemetryEmitter` protocol:

  - `StdoutTelemetry`: prints each event as a JSON line to stdout.
    Used in local dev; a developer can `tail -f` and watch events
    flow. No external dependencies.

  - `AppInsightsTelemetry`: emits to Azure Application Insights via
    OpenTelemetry. Stub for Batch 7 — the actual Azure SDK wiring
    lands with the rest of the cloud infrastructure. The stub raises
    on construction so a misconfigured cloud deploy fails loudly.

Both adapters swallow internal emission errors (caught + logged at
WARNING) so that an event sink failure can never break the user's
request.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any


logger = logging.getLogger(__name__)


class StdoutTelemetry:
    """Emit events as JSON lines to stdout.

    Format is intentionally one-line JSON so it can be piped to `jq`
    or grepped easily. No timestamps in the payload itself — uvicorn
    and the surrounding logger already prefix lines with timestamps.
    """

    def emit_event(self, name: str, fields: dict[str, Any]) -> None:
        try:
            payload = {"event": name, **fields}
            line = json.dumps(payload, default=str, ensure_ascii=False)
            sys.stdout.write(f"TELEMETRY {line}\n")
            sys.stdout.flush()
        except Exception as e:
            # NEVER let telemetry kill the request.
            logger.warning("StdoutTelemetry emit failed: %s: %s",
                           type(e).__name__, e)


class AppInsightsTelemetry:
    """Stub for Application Insights. Real implementation in Batch 7.

    The constructor raises so that a cloud deploy without the matching
    Batch 7 work fails fast and visibly. Replacing this with the real
    `opencensus-ext-azure` / `opentelemetry-azuremonitor` integration
    is a Batch 7 deliverable.
    """

    def __init__(self, connection_string: str) -> None:
        raise NotImplementedError(
            "AppInsightsTelemetry not yet implemented; "
            "real Azure SDK wiring ships with Batch 7 (Azure IaC). "
            "For local dev set environment=local to use StdoutTelemetry."
        )

    def emit_event(self, name: str, fields: dict[str, Any]) -> None:
        # Unreachable — __init__ raises.
        raise NotImplementedError