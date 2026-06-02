"""Health check endpoints.

`/api/health` is a lightweight liveness probe. Returns 200 OK as long
as the process is running. Does NOT exercise the index, the LLM, or
any external dependency — those are checked in `/api/health/ready`
(reserved for a later chunk, not in scope for Batch 4 since UptimeRobot
will hit `/api/health` and a cold-start ChromaDB load would dominate
the latency of every check).

For Container Apps' health probes, the platform expects a quick 200
response. The current implementation completes in ~milliseconds.
"""

from __future__ import annotations

import time

from fastapi import APIRouter
from pydantic import BaseModel


router = APIRouter()


# Module-level start time; first import locks it in. Used to report
# uptime in seconds, useful for sanity-checking that scale-to-zero just
# spun up a fresh container.
_PROCESS_START_TIME: float = time.time()


class HealthResponse(BaseModel):
    """Minimal liveness payload."""

    status: str = "ok"
    uptime_seconds: float


@router.get("/api/health", response_model=HealthResponse, tags=["health"])
async def health() -> HealthResponse:
    return HealthResponse(uptime_seconds=time.time() - _PROCESS_START_TIME)