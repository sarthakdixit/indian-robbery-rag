"""Structured-telemetry emitter Protocol.

Distinct from `logging` (which is a per-process event stream): telemetry
is the *durable, queryable* version of that — events that an operator
or admin dashboard will read back later. In Azure cloud deploy this
goes to Application Insights via OpenTelemetry. In local dev it goes
to stdout (so a developer can `tail -f` and see structured events).

Why not just use the structlog logger for both? Because Application
Insights is a *sink*, not a logger replacement. Structlog handles
formatting and binding (correlation ids, contextvars); the telemetry
emitter handles the destination. Splitting them keeps the local/cloud
adapter pattern (AGENT.md §2.1) clean.

This Protocol is intentionally minimal — only `emit_event(name, fields)`.
Adapter implementations can use it for anything (request lifecycle, RAG
pipeline stages, errors). The contract is: synchronous-looking but
infrastructure may queue/batch.

The QueryLogWriter (chunk 4.4) writes to DocumentStore separately; it
is NOT a TelemetryEmitter. The distinction: telemetry events are for
*operator observability*, query logs are for the *admin dashboard*.
They could overlap but the storage and retention model are different.
"""

from __future__ import annotations

from typing import Any, Protocol


class TelemetryEmitter(Protocol):
    """Emit a structured telemetry event.

    `name` is a short event identifier (snake_case recommended).
    `fields` is a flat dict of additional context. Implementations
    should NOT mutate the dict; copy if needed.

    Implementations must be safe to call from any async coroutine
    without external locking. Errors during emission MUST be caught and
    swallowed (with internal logging) — telemetry should never fail the
    caller's request.
    """

    def emit_event(self, name: str, fields: dict[str, Any]) -> None:
        ...