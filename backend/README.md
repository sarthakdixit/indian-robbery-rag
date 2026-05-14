# backend/

The Python FastAPI service that powers the RAG pipeline.

## Purpose

This module serves the `/api/query`, `/api/health`, and `/api/admin/*` HTTP endpoints. It performs hybrid retrieval against ChromaDB, calls Gemini for embeddings and generation, verifies citations, enforces rate limiting and abuse protection, and writes telemetry to Cosmos DB (cloud) or SQLite (local).

It does **not** ingest the corpus. That happens offline in [`../ingestion/`](../ingestion/) and produces a ChromaDB folder that the backend reads at startup.

## Layout

See [`AGENT.md` §13.1](../AGENT.md#131-backend-layout) for the authoritative directory structure. The shape:

```
backend/
├── app/
│   ├── main.py                FastAPI app construction, container wiring
│   ├── config.py              Settings (pydantic-settings)
│   ├── container.py           dependency-injector container
│   ├── errors.py              Exception hierarchy
│   ├── constants.py           Domain-wide constants
│   ├── protocols/             Interface definitions (Protocol classes)
│   ├── adapters/              Concrete implementations (local + cloud)
│   ├── rag/                   Retrieval, generation, citation pipeline
│   ├── cache/                 Two-layer cache (exact + semantic)
│   ├── security/              Rate limiting, IP hashing, Turnstile, circuit breaker
│   ├── telemetry/             Query logs, counters, cost tracker
│   ├── routes/                FastAPI route handlers
│   ├── schemas/               Pydantic request/response models
│   └── middleware/            Request context, structured logging
├── tests/
│   ├── unit/                  Pure logic, no I/O
│   ├── integration/           Real adapters, real Gemini
│   └── contract/              Same test, runs against local AND cloud adapters
├── Dockerfile
├── requirements.txt
├── requirements-dev.txt
├── pyproject.toml
└── .env.example
```

## Status

Empty scaffolding. Files arrive over Batches 3-5:

- **Batch 3** — RAG core (config, clients, retrieval, generation, citation, caching)
- **Batch 4** — HTTP service (FastAPI routes, rate limiting, Turnstile, circuit breaker, logging)
- **Batch 5** — Admin endpoints, Docker packaging, local dev tooling

## Coding Conventions

Read [`../AGENT.md`](../AGENT.md) before writing any code here. Key rules in short form:

- `mypy --strict` clean
- Dependency injection via `dependency-injector` — no concrete cloud SDK imports in business logic
- Local-first: every external dependency has a `Local*` and a `Cloud*` adapter
- Async I/O (FastAPI is async); sync only allowed inside `ingestion/`

## Local Development

_Quick-start commands will land with Batch 5._

The intent: `make dev` runs the full backend locally with a Gemini API key in `.env` and no Azure access needed.
