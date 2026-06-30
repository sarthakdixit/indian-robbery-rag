"""Telemetry adapter implementations.

Two implementations of the `TelemetryEmitter` protocol:

  - `StdoutTelemetry`: prints each event as a JSON line to stdout.
    Used in local dev; a developer can `tail -f` and watch events
    flow. No external dependencies.

  - `AppInsightsTelemetry`: emits to Azure Application Insights via
    OpenTelemetry's logs API. Uses the documented `microsoft.custom_event.name`
    attribute pattern so events show up in the App Insights
    customEvents table. See:
    https://learn.microsoft.com/azure/azure-monitor/app/opentelemetry-add-modify

Both adapters swallow internal emission errors (caught + logged at
WARNING) so that an event sink failure can never break the user's
request.
"""

from __future__ import annotations

import json
import logging
import sys
import threading
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


# Module-level flag — `configure_azure_monitor` must be called exactly
# once per process. The DI container builds AppInsightsTelemetry as a
# Singleton so concurrent construction shouldn't happen, but a defensive
# lock guards the bootstrap regardless (tests can construct from the
# same process; reloaders might too).
_AZURE_MONITOR_CONFIGURED = False
_AZURE_MONITOR_LOCK = threading.Lock()


class AppInsightsTelemetry:
    """Emit events to Application Insights via OpenTelemetry.

    The connection string follows the standard App Insights format
    (e.g., "InstrumentationKey=...;IngestionEndpoint=..."). Container
    Apps injects this from a Key Vault reference at startup; Settings
    reads it from APPLICATIONINSIGHTS_CONNECTION_STRING.

    Each `emit_event` call produces ONE OpenTelemetry log record with
    the special `microsoft.custom_event.name` attribute set, which the
    App Insights ingestion pipeline maps to the customEvents table.
    Other fields are flattened to attributes.

    Failure mode: if OTel setup fails (bad connection string, network
    unreachable, missing optional deps), we log and fall through to
    stdout — the user's request still completes. Telemetry is best-
    effort by design.
    """

    def __init__(self, connection_string: str) -> None:
        self._configured = False
        self._otel_logger: Any | None = None
        try:
            self._ensure_configured(connection_string)
        except Exception as e:
            # Log loudly but DO NOT raise. A broken telemetry adapter
            # must never prevent the app from starting.
            logger.error(
                "AppInsightsTelemetry init failed; events will fall back "
                "to stdout. Cause: %s: %s",
                type(e).__name__, e,
            )

    def _ensure_configured(self, connection_string: str) -> None:
        global _AZURE_MONITOR_CONFIGURED
        with _AZURE_MONITOR_LOCK:
            if not _AZURE_MONITOR_CONFIGURED:
                # Imports are lazy because the azure-monitor-opentelemetry
                # package pulls in OpenTelemetry deps (~30MB). We don't
                # want to pay that cost in local-mode processes that
                # never construct this adapter.
                from azure.monitor.opentelemetry import (  # type: ignore[import-untyped]
                    configure_azure_monitor,
                )

                configure_azure_monitor(
                    connection_string=connection_string,
                    # Logs are what we use for custom events. Traces and
                    # metrics auto-instrument FastAPI; we leave defaults
                    # on so request spans appear in App Insights too.
                )
                _AZURE_MONITOR_CONFIGURED = True
                logger.info("Azure Monitor configured for App Insights export")

            from opentelemetry._logs import (  # type: ignore[import-untyped]
                get_logger_provider,
            )
            self._otel_logger = get_logger_provider().get_logger(
                "robbery-rag-backend",
            )
            self._configured = True

    def emit_event(self, name: str, fields: dict[str, Any]) -> None:
        if not self._configured or self._otel_logger is None:
            # Fall back to stdout so the event isn't lost.
            try:
                payload = {"event": name, **fields}
                sys.stdout.write(f"TELEMETRY {json.dumps(payload, default=str)}\n")
                sys.stdout.flush()
            except Exception:
                pass
            return

        try:
            from opentelemetry._logs import (  # type: ignore[import-untyped]
                SeverityNumber,
            )
            from opentelemetry.sdk._logs import LogRecord  # type: ignore[import-untyped]

            # Flatten field values — OTel attributes don't accept
            # nested types. Stringify anything non-scalar.
            flat_attrs: dict[str, Any] = {"microsoft.custom_event.name": name}
            for k, v in fields.items():
                if isinstance(v, (str, int, float, bool)) or v is None:
                    flat_attrs[k] = v
                else:
                    flat_attrs[k] = json.dumps(v, default=str)

            record = LogRecord(
                body=name,
                severity_number=SeverityNumber.INFO,
                attributes=flat_attrs,
            )
            self._otel_logger.emit(record)
        except Exception as e:
            logger.warning(
                "AppInsightsTelemetry emit failed: %s: %s",
                type(e).__name__, e,
            )