"""FastAPI application entry point.

Construction order (matters):
  1. Logging is configured before anything else, so subsequent
     construction errors are visible.
  2. The DI container is instantiated and wired against the route
     modules. Wiring must complete before the first request is served,
     so we do it at module import time rather than in a lifespan event.
  3. The FastAPI app is built with middleware, exception handlers, and
     routers attached.
  4. The container is stashed on `app.state` for downstream tooling
     (tests, admin scripts, etc.) that need to inspect or override
     providers.

Running locally:

    uvicorn backend.app.main:app --reload --port 8000

Hitting POST /api/query with a JSON body matching the QueryRequest
schema returns the same envelope you'd get from
`python -m backend.app.rag.pipeline`, but via HTTP. The turnstile_token
is accepted but not verified yet (real verification lands in Chunk 4.3).

The exception handler maps `AppError` subclasses to typed JSON
responses. Adapter-layer errors (Gemini, ChromaDB, etc.) are translated
inside individual route handlers, not here — that keeps the handler
layer ignorant of which adapter raised what.
"""

from __future__ import annotations

import logging
import sys

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from backend.app.config import get_settings
from backend.app.container import Container
from backend.app.errors import AppError
from backend.app.middleware.request_context import RequestContextMiddleware
from backend.app.routes import admin as admin_routes
from backend.app.routes import health as health_routes
from backend.app.routes import query as query_routes


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
# Per AGENT.md §10 we use structlog in business code, but the FastAPI/uvicorn
# stack itself uses stdlib logging. Configure the stdlib root so framework
# logs (uvicorn access log, route logs) land in a useful format. Structlog
# configuration lands in Chunk 4.4 alongside the rest of telemetry.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Container wiring
# ---------------------------------------------------------------------------
# The container must be wired BEFORE FastAPI starts serving. We wire at
# module-import time (i.e., before any request hits the app) per
# AGENT.md §17.1. The container is stashed on `app.state` so tests can
# reach it via the standard FastAPI TestClient pattern:
#     client.app.state.container.exact_cache.override(...)
container = Container()
container.wire(
    modules=[
        "backend.app.routes.query",
        "backend.app.routes.admin",
    ]
)


# ---------------------------------------------------------------------------
# App construction
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Indian Robbery Law RAG",
    description=(
        "A research assistant for Indian criminal law on robbery offences "
        "under the BNS, 2023 and the IPC, 1860."
    ),
    version="0.4.1",
)
app.state.container = container


# Middleware. Order is bottom-up: middlewares added LAST run FIRST on
# inbound requests. We have only one for now; ordering becomes important
# when we add a global-cap middleware in Chunk 4.2.
_settings = get_settings()
app.add_middleware(
    RequestContextMiddleware,
    salt=_settings.ip_hash_salt.get_secret_value(),
)

# CORS — added LAST so it's OUTERMOST and handles preflight OPTIONS
# requests before any other middleware sees them.
#
# In local dev the frontend runs at http://localhost:5173 (Vite default)
# and the backend at http://localhost:8000. Cross-origin → CORS required.
#
# Allowed origins are environment-specific:
#   local: localhost:5173 (Vite dev), localhost:4173 (Vite preview)
#   cloud: the SWA hostname (set via env in Batch 7)
#
# `allow_credentials=False` is fine — we use header-based auth
# (x-admin-password) on admin routes, not cookies. If we ever add
# cookies, this needs to flip True AND allow_origins can't be ["*"].
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

_cors_origins: list[str] = [
    "http://localhost:5173",  # Vite dev server
    "http://localhost:4173",  # Vite preview server
    "http://127.0.0.1:5173",
    "http://127.0.0.1:4173",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "x-admin-password"],
    expose_headers=["x-request-id"],
)


# ---------------------------------------------------------------------------
# Exception handler — AppError → typed JSON response
# ---------------------------------------------------------------------------
@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "no-request-id")
    logger.info(
        "app error: request_id=%s code=%s status=%d msg=%s",
        request_id, exc.error_code, exc.http_status, exc,
    )
    return JSONResponse(
        status_code=exc.http_status,
        content={
            "error_code": exc.error_code,
            "message": str(exc) or exc.error_code,
            "request_id": request_id,
        },
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
app.include_router(health_routes.router)
app.include_router(query_routes.router)
app.include_router(admin_routes.router)


# Sanity log so a developer running `uvicorn ...` immediately sees the
# environment and container state.
logger.info(
    "FastAPI app constructed: environment=%s, gemini_model=%s, "
    "corpus_version=%s",
    _settings.environment,
    _settings.gemini_generation_model,
    container.corpus_version(),
)