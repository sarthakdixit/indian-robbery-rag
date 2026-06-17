# AGENT.md — Python Coding Conventions

> **Audience:** AI coding agents and human contributors writing Python for this repository.
> **Status:** Authoritative. When this file conflicts with code, the code is wrong.
> **Scope:** Applies to `backend/`, `ingestion/`, and `eval/`. Frontend has its own conventions and ships as a separate ZIP.

---

## Table of Contents

1. [Core Principles](#1-core-principles)
2. [Local-First Development](#2-local-first-development)
3. [Dependency Injection](#3-dependency-injection)
4. [Naming & Self-Documenting Code](#4-naming--self-documenting-code)
5. [Comments & Docstrings](#5-comments--docstrings)
6. [Type Hints](#6-type-hints)
7. [Async Conventions](#7-async-conventions)
8. [Configuration & Secrets](#8-configuration--secrets)
9. [Error Handling](#9-error-handling)
10. [Logging](#10-logging)
11. [Testing](#11-testing)
12. [Pydantic Usage](#12-pydantic-usage)
13. [File Organization](#13-file-organization)
14. [Linting, Formatting & Type Checking](#14-linting-formatting--type-checking)
15. [Constants & Magic Values](#15-constants--magic-values)
16. [Common Anti-Patterns](#16-common-anti-patterns)
17. [Library-Specific Notes](#17-library-specific-notes)

---

## 1. Core Principles

These five principles override any rule in this document if there is a conflict.

1. **Local first, cloud later.** Every feature works end-to-end on a developer laptop with no Azure access. Cloud is an adapter swap.
2. **Inject everything external.** No business logic imports a concrete cloud SDK. All external dependencies are abstracted behind interfaces and wired in the DI container.
3. **Names over comments.** A function name should answer "what does this do?" without needing a comment.
4. **Types over docstrings.** A signature should answer "what does this take and return?" without prose.
5. **Strict by default.** `mypy --strict`, `ruff check`, and `pytest` must all be green before any merge.

---

## 2. Local-First Development

Every external dependency has a **local adapter** and a **cloud adapter** behind a shared interface. Tests use local adapters. Local development uses local adapters. Cloud deployment uses cloud adapters. Switching is a single config flag.

### 2.1 Mapping

| Service              | Cloud adapter                 | Local adapter                  | Activation                                 |
| -------------------- | ----------------------------- | ------------------------------ | ------------------------------------------ |
| Cosmos DB            | `CosmosDocumentStore`         | `SQLiteDocumentStore`          | `ENVIRONMENT=cloud` vs `local`             |
| Key Vault            | `KeyVaultSecretsProvider`     | `DotEnvSecretsProvider`        | same                                       |
| Application Insights | `AppInsightsTelemetry`        | `StdoutTelemetry`              | same                                       |
| Cloudflare Turnstile | `CloudflareTurnstileVerifier` | `AlwaysValidTurnstileVerifier` | same                                       |
| Gemini API           | `GeminiClient`                | `GeminiClient` (same)          | Gemini is always real; mock only in tests  |
| ChromaDB             | `ChromaVectorStore`           | `ChromaVectorStore` (same)     | ChromaDB is embedded, identical everywhere |

ChromaDB and Gemini do not need local/cloud adapters because ChromaDB is embedded (it is always "local" to the running process) and Gemini's free tier is used in both environments. Mocks for these exist only for tests.

### 2.2 Required Capabilities of the Local Stack

The local stack must support, with no Azure access:

- Full RAG pipeline (retrieve, generate, cite, verify)
- Rate limiting with persistent counters across restarts
- Caching with persistence
- Query logs queryable from the admin endpoint
- Cost tracking and circuit breaker
- Turnstile bypass for development

Local development must be runnable with: `make dev` (no other prerequisites beyond Python, `uv` or `pip`, and a Gemini API key in `.env`).

### 2.3 SQLite as Cosmos Replacement

The local document store uses SQLite with a single `documents` table that mirrors the Cosmos partition-key + id + JSON-body shape:

```python
class SQLiteDocumentStore(DocumentStore):
    async def upsert(self, partition_key: str, doc_id: str, body: dict[str, Any]) -> None: ...
    async def get(self, partition_key: str, doc_id: str) -> dict[str, Any] | None: ...
    async def query(self, partition_key: str, where: dict[str, Any]) -> list[dict[str, Any]]: ...
    async def delete(self, partition_key: str, doc_id: str) -> None: ...
```

The schema is intentionally identical to Cosmos's partition-key-and-id model so that adapter swap is a wiring change, not a code change.

---

## 3. Dependency Injection

The project uses [`dependency-injector`](https://python-dependency-injector.ets-labs.org/) for all wiring. Business logic never imports concrete cloud classes.

### 3.1 Container Structure

A single `Container` class in `backend/app/container.py` defines all providers. Containers are composed into sub-containers per domain (`security`, `rag`, `cache`, `telemetry`). The active container is selected at startup based on `ENVIRONMENT`.

### 3.2 Provider Pattern

```python
from dependency_injector import containers, providers
from backend.app.protocols.document_store import DocumentStore
from backend.app.adapters.sqlite import SQLiteDocumentStore
from backend.app.adapters.cosmos import CosmosDocumentStore

class StorageContainer(containers.DeclarativeContainer):
    config = providers.Configuration()

    document_store: providers.Provider[DocumentStore] = providers.Selector(
        config.environment,
        local=providers.Singleton(SQLiteDocumentStore, db_path=config.sqlite_path),
        cloud=providers.Singleton(CosmosDocumentStore, connection_string=config.cosmos_connection),
    )
```

### 3.3 Injecting Into FastAPI Routes

Use the `@inject` decorator and wrap the `Provide[]` marker in `Depends()`. Never instantiate adapters inside route handlers.

```python
from dependency_injector.wiring import inject, Provide
from fastapi import Depends
from backend.app.container import Container

@router.post("/query")
@inject
async def query_endpoint(
    request: QueryRequest,
    rate_limiter: RateLimiter = Depends(Provide[Container.rate_limiter]),
    pipeline: Pipeline = Depends(Provide[Container.pipeline]),
) -> QueryResponse:
    ...
```

**Why `Depends(Provide[...])` and not bare `Provide[...]`:** without the `Depends()` wrapper, FastAPI parses the dependency parameter as a request-body Pydantic field (because the default has no signal that it's a dependency). The handler then fails at request time with a confusing schema error. Wrapping `Provide[...]` in `Depends()` tells FastAPI "this is an injected dependency, not body data."

**Why NOT the `Annotated[T, Depends(Provide[Container.x])]` form:** this is the pattern the dependency-injector docs sometimes suggest, but as of dependency-injector 4.49 it has a known bug (`'Provide' object has no attribute X'`; GitHub issues #767 and #850). The non-Annotated form above is reliable.

### 3.4 Rules

- **Protocols/interfaces live in `backend/app/protocols/`.** Concrete adapters live in `backend/app/adapters/`.
- **No `from azure.cosmos import ...` outside `backend/app/adapters/cosmos.py`.** Same rule for every cloud SDK.
- **No `os.environ` lookups outside `config.py`.** Settings are injected.
- **No global singletons.** Use the container.
- **Tests build a test container** that injects local adapters and in-memory fakes.

### 3.5 Adapter Contract

Every cloud-replaceable dependency MUST:

1. Have a `Protocol` definition in `backend/app/protocols/`.
2. Have at least two implementations: `Local*` and `Cloud*` (or `Azure*`, `Cosmos*`, etc.).
3. Be wired through the container with `providers.Selector`.
4. Have tests covering both implementations with the same test cases.

---

## 4. Naming & Self-Documenting Code

Names are the primary documentation mechanism.

### 4.1 Function & Method Names

Verbs that describe the action, with enough specificity to remove ambiguity.

```python
# Good
async def fetch_rate_limit_count_for_hashed_ip(hashed_ip: str) -> int: ...
async def store_query_log_entry(entry: QueryLogEntry) -> None: ...
def normalize_query_for_exact_cache_lookup(query: str) -> str: ...

# Bad
def get_count(ip: str) -> int: ...
def save(entry: dict) -> None: ...
def norm(q: str) -> str: ...
```

### 4.2 Class Names

Noun phrases. Suffix indicates role: `*Service`, `*Repository`, `*Client`, `*Adapter`, `*Verifier`, `*Tracker`, `*Pipeline`. Avoid `*Manager` and `*Helper` — they hide responsibility.

```python
# Good
class SemanticCacheLookup: ...
class CitationVerifier: ...
class RateLimitRepository: ...
class GeminiGenerationClient: ...

# Bad
class CacheManager: ...
class CitationHelper: ...
class RateLimitStuff: ...
```

### 4.3 Variable Names

Full words. `i`, `j`, `k` allowed only in tight loops. `tmp`, `data`, `result` are forbidden as final variable names — they are placeholders, not names.

```python
# Good
retrieved_chunks: list[Chunk] = await retriever.retrieve(query)
top_similarity_score: float = retrieved_chunks[0].score

# Bad
data = await retriever.retrieve(query)
result = data[0].score
```

### 4.4 Boolean Names

Prefix with `is_`, `has_`, `should_`, `can_`. Booleans read as predicates.

```python
is_within_scope: bool
has_valid_turnstile_token: bool
should_bypass_cache: bool
can_serve_from_semantic_cache: bool
```

### 4.5 Constant Names

`UPPER_SNAKE_CASE`. Lives in a `constants.py` module per domain, never inline.

```python
SCOPE_REJECTION_SIMILARITY_THRESHOLD: float = 0.55
SEMANTIC_CACHE_HIT_THRESHOLD: float = 0.92
PER_IP_DAILY_QUERY_LIMIT: int = 5
GLOBAL_DAILY_QUERY_CAP: int = 200
```

---

## 5. Comments & Docstrings

### 5.1 No "What" Comments

If a comment describes what the next line does, the code needs better names.

```python
# Bad
# Increment the counter
counter += 1

# Bad
# Check if rate limit is exceeded
if count > limit:

# Good — the code is already self-explanatory
counter += 1
if query_count_for_ip > PER_IP_DAILY_QUERY_LIMIT:
```

### 5.2 "Why" Comments Are Allowed

When the _reason_ for code is non-obvious and cannot be encoded in names, a comment is justified. These should explain context, trade-offs, or external constraints.

```python
# Threshold tuned empirically against the eval set — pairs below 0.92 produced
# wrong-cache-hits on legally distinct robbery vs dacoity queries. See eval/results/threshold_sweep.md
SEMANTIC_CACHE_HIT_THRESHOLD: float = 0.92

# Cosmos returns 429 with retry_after_ms during burst writes; we honor it rather than
# our own backoff because the server-suggested value reflects current partition load.
```

### 5.3 Docstrings

One-line docstrings allowed on **public** classes and functions (anything imported by another module). Skip docstrings on:

- Private functions (leading underscore)
- Methods whose name + signature is fully self-describing
- Adapters that implement a Protocol (the Protocol carries the docstring)

```python
class CitationVerifier:
    """Strips citations from a generated answer that do not appear in the retrieved chunk set."""

    async def verify(self, answer: GeneratedAnswer, retrieved: list[Chunk]) -> VerifiedAnswer:
        ...
```

### 5.4 TODO and FIXME

Allowed but must include a GitHub issue link or owner.

```python
# TODO(#42): Replace cosine similarity with cross-encoder re-ranker after v1.
```

Bare `# TODO` without context is rejected by CI.

---

## 6. Type Hints

Mandatory everywhere. `mypy --strict` must pass.

### 6.1 Coverage Rules

- Every function parameter has a type annotation.
- Every function return type is annotated, including `-> None`.
- Every class attribute is annotated (use `@dataclass` or Pydantic where it fits).
- No `Any` without a `# type: ignore[explicit-any]` and a "why" comment.
- No untyped `dict` or `list` — always parameterize: `dict[str, int]`, `list[Chunk]`.

### 6.2 Modern Syntax

Python 3.11+ syntax. Do not import from `typing` what is built-in.

```python
# Good
def foo(items: list[str], mapping: dict[str, int] | None = None) -> tuple[int, str]: ...

# Bad — old syntax
from typing import List, Dict, Optional, Tuple
def foo(items: List[str], mapping: Optional[Dict[str, int]] = None) -> Tuple[int, str]: ...
```

### 6.3 Protocols for Interfaces

Use `typing.Protocol` for dependency interfaces. Avoid abstract base classes unless inheritance is genuinely needed.

```python
from typing import Protocol

class DocumentStore(Protocol):
    async def upsert(self, partition_key: str, doc_id: str, body: dict[str, Any]) -> None: ...
    async def get(self, partition_key: str, doc_id: str) -> dict[str, Any] | None: ...
```

### 6.4 Mypy Strict Edge Cases

Some third-party packages lack stubs. The only acceptable mitigation is the targeted ignore at the import site, with a brief justification:

```python
import chromadb  # type: ignore[import-untyped]  # No official stubs as of project start.
```

Configure these once in `mypy.ini`:

```ini
[mypy]
strict = True
python_version = 3.11

[mypy-chromadb.*]
ignore_missing_imports = True

[mypy-google.generativeai.*]
ignore_missing_imports = True
```

### 6.5 Forbidden Patterns

- `def foo(x):` — missing annotation
- `def foo(x: Any) -> Any:` without justification
- `cast(SomeType, value)` without a comment explaining why
- `# type: ignore` without a specific error code

---

## 7. Async Conventions

FastAPI is async. All I/O must be async.

### 7.1 Rules

- All HTTP, database, and external API calls use `async def` and `await`.
- Never call a synchronous I/O function from an async context without `asyncio.to_thread`.
- No `time.sleep()` — use `asyncio.sleep()`.
- No `requests` library — use `httpx.AsyncClient`.
- Use `async with` for resource management (HTTP clients, DB connections).

### 7.2 Sync Code Is Allowed Only For

- Pure CPU work with no I/O (chunking text, hashing, regex matching).
- **Ingestion scripts that run offline** (these are batch jobs, sync is fine). This includes everything under `ingestion/`: `collect/`, `classify/` (the Gemini relevance classifier), `normalize/` (BeautifulSoup HTML parsing, PDF parsing), `chunk/`, `embed/`, and `index/`. These scripts run once locally and produce static artifacts; async is overhead without benefit. For Gemini calls from these scripts, the **sync** Gemini SDK methods (`generate_content`, not `generate_content_async`) are acceptable.
- ChromaDB queries (current ChromaDB client is sync — wrap in `asyncio.to_thread` when called from async code).

### 7.3 ChromaDB Async Wrapper

```python
class ChromaVectorStore:
    async def search(self, query_embedding: list[float], top_k: int) -> list[Chunk]:
        return await asyncio.to_thread(self._search_sync, query_embedding, top_k)

    def _search_sync(self, query_embedding: list[float], top_k: int) -> list[Chunk]: ...
```

---

## 8. Configuration & Secrets

### 8.1 Pydantic BaseSettings

All configuration goes through a single `Settings` class using `pydantic-settings`. Reads from environment variables; in local development, loads from `.env`.

```python
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="forbid")

    environment: Literal["local", "cloud"] = "local"
    gemini_api_key: SecretStr
    cosmos_connection_string: SecretStr | None = None
    sqlite_path: Path = Path("./local_data/app.db")
    per_ip_daily_query_limit: int = 5
    global_daily_query_cap: int = 200
    semantic_cache_threshold: float = 0.92
    scope_rejection_threshold: float = 0.55
```

### 8.2 Rules

- No `os.environ.get(...)` calls outside `config.py`.
- No hardcoded secrets, ever. Even local development uses `.env` (which is gitignored).
- `.env.example` is committed and lists every variable with a placeholder value and a one-line description.
- Secrets are typed `SecretStr` so they do not accidentally print.

### 8.3 Local vs Cloud Secrets

Locally: `.env` file → `pydantic-settings` reads it.
In cloud: Container Apps secrets reference Key Vault via `keyvaultref:` → injected as env vars → `pydantic-settings` reads them identically.

The application code never knows the difference.

---

## 9. Error Handling

### 9.1 Custom Exception Hierarchy

Every distinct failure mode is its own exception class. Defined in `backend/app/errors.py`.

```python
class AppError(Exception):
    """Base class for all application errors."""
    http_status: int = 500
    error_code: str = "internal_error"

class RateLimitExceeded(AppError):
    http_status = 429
    error_code = "rate_limit_exceeded"

class OutOfScope(AppError):
    http_status = 200
    error_code = "out_of_scope"

class TurnstileVerificationFailed(AppError):
    http_status = 403
    error_code = "turnstile_failed"

class GlobalCapReached(AppError):
    http_status = 503
    error_code = "demo_at_capacity"

class CircuitBreakerOpen(AppError):
    http_status = 503
    error_code = "llm_unavailable"

class CitationVerificationFailed(AppError):
    http_status = 500
    error_code = "citation_verification_failed"
```

### 9.2 Rules

- **No bare `except:`.** Always specify the exception type.
- **No `except Exception:` without re-raising or logging.** If you catch broadly, you log and re-raise as a typed `AppError`.
- **FastAPI exception handlers** translate `AppError` subclasses to HTTP responses. One handler covers all of them.
- **Boundary errors get translated.** A `CosmosResourceNotFoundError` from the SDK never propagates past the adapter layer — it becomes `DocumentNotFound` or returns `None`.

### 9.3 The Exception Handler Pattern

```python
@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.http_status,
        content={"error_code": exc.error_code, "message": str(exc)},
    )
```

Out-of-scope returns HTTP 200 with `error_code: "out_of_scope"` rather than a 4xx, because it's a successful classification, not a client error.

---

## 10. Logging

### 10.1 Structured Logging Only

Use `structlog`. No `print()`. No `logging.info(f"...")`. Every log line is a structured event with named fields.

```python
import structlog

logger = structlog.get_logger(__name__)

await logger.ainfo(
    "query_processed",
    request_id=request_id,
    hashed_ip=hashed_ip,
    latency_ms=latency_ms,
    cache_hit=cache_hit,
    retrieved_chunk_count=len(chunks),
    citation_count=len(citations),
)
```

### 10.2 Required Fields on Every Request Log

- `request_id` — UUID generated in middleware
- `hashed_ip` — SHA-256(IP + salt)
- `endpoint` — route path
- `latency_ms` — total time
- `status_code` — HTTP status

### 10.3 PII Rules

- **Never log raw IP addresses.** Always the salted hash.
- **Question text is allowed in logs** (no PII concern for an anonymous educational demo, and required for analytics).
- **Response text is allowed in logs** for the admin dashboard.
- **API keys, secrets, tokens are forbidden.** Use `SecretStr` and filter at the log adapter.

### 10.4 Log Levels

- `debug` — local dev only, off in production
- `info` — request lifecycle, normal operations
- `warning` — recoverable issues (cache miss, retry succeeded)
- `error` — failures requiring attention (Cosmos timeout, Gemini failure)
- `critical` — circuit breaker tripped, global cap hit

---

## 11. Testing

### 11.1 Framework

`pytest` + `pytest-asyncio`. No `unittest`.

### 11.2 Test Layout

```
backend/tests/
  unit/           # No I/O, no DI container. Pure logic.
  integration/   # Uses test DI container with local adapters.
  contract/      # Same test, runs against both local and cloud adapters.
```

### 11.3 Use the DI Container in Tests

Tests build a test container that injects local adapters. No `unittest.mock` magic for things the DI container can swap.

```python
@pytest.fixture
def test_container() -> Container:
    container = Container()
    container.config.environment.from_value("local")
    container.config.sqlite_path.from_value(":memory:")
    return container
```

### 11.4 What to Test

- **Unit tests:** Pure logic — chunking, citation parsing, prompt building, cache key generation, similarity threshold logic.
- **Integration tests:** Adapter implementations (SQLite store actually writes, Gemini client actually parses responses). Use real Gemini with a test API key budget.
- **Contract tests:** The same test class runs against `SQLiteDocumentStore` and `CosmosDocumentStore` (the cloud variant is opt-in via env var).
- **Eval set is not a unit test.** It is a separate harness in `eval/` invoked via `python eval/run_eval.py`.

### 11.5 Coverage

Target ~80% line coverage on `backend/app/`. Coverage is informational, not a CI gate (gaming coverage produces worse code).

### 11.6 No Snapshot Tests

LLM outputs are non-deterministic. Test the _shape_ of responses (citations present, fields populated), not exact text.

---

## 12. Pydantic Usage

### 12.1 Pydantic Models For

- All HTTP request and response bodies.
- All Cosmos / SQLite document bodies (stored as JSON, parsed into models on read).
- All cross-module DTOs that travel between layers.
- All configuration (via `BaseSettings`).

### 12.2 Dataclasses For

- Internal value objects that never cross a boundary (e.g., an intermediate retrieval result inside the pipeline).
- Performance-critical paths where Pydantic validation overhead matters.

When in doubt, use Pydantic. The validation safety is worth more than the microseconds.

### 12.3 Strict Validation

```python
class QueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    question: str = Field(min_length=3, max_length=1000)
    turnstile_token: str = Field(min_length=1)
```

`extra="forbid"` rejects unknown fields. This catches typos and prevents accidental schema drift.

### 12.4 Response Models

Every FastAPI route declares a `response_model`:

```python
@router.post("/query", response_model=QueryResponse)
async def query(...) -> QueryResponse: ...
```

This auto-generates the OpenAPI schema, which drives the frontend's typed API client.

---

## 13. File Organization

### 13.1 Backend Layout

```
backend/
  app/
    __init__.py
    main.py                     # FastAPI app construction, container wiring
    config.py                   # Settings (BaseSettings)
    container.py                # dependency-injector Container
    errors.py                   # Exception hierarchy
    constants.py                # Domain-wide constants (re-exports from sub-packages)
    protocols/                  # Interface definitions (Protocol classes)
      document_store.py
      secrets_provider.py
      telemetry.py
      turnstile_verifier.py
    adapters/                   # Concrete implementations
      sqlite_document_store.py
      cosmos_document_store.py
      dotenv_secrets_provider.py
      key_vault_secrets_provider.py
      stdout_telemetry.py
      app_insights_telemetry.py
      always_valid_turnstile_verifier.py
      cloudflare_turnstile_verifier.py
    rag/                        # RAG pipeline
      retrieval.py
      bm25.py
      hybrid.py
      scope.py
      prompt.py
      generate.py
      citations.py
      pipeline.py
    cache/
      exact.py
      semantic.py
      manager.py
      keys.py
    security/
      ip.py
      rate_limit.py
      global_cap.py
      circuit_breaker.py
    telemetry/
      query_log.py
      counters.py
      cost_tracker.py
    routes/
      query.py
      health.py
      admin.py
    schemas/                    # Pydantic request/response models
      request.py
      response.py
    middleware/
      request_context.py
  tests/
    unit/
    integration/
    contract/
```

### 13.2 Module Rules

- One class per file when the class is non-trivial (> 30 lines).
- Group small related functions in one module (e.g., `keys.py` has `make_exact_cache_key`, `make_semantic_cache_key`).
- 300 lines soft cap, 500 lines hard cap (per `design.md`).
- No circular imports. If you hit one, the dependency direction is wrong — extract a Protocol.

### 13.3 Import Order

Enforced by Ruff:

1. Standard library
2. Third-party
3. First-party (`backend.app.*`)
4. Relative imports (avoid; prefer absolute)

---

## 14. Linting, Formatting & Type Checking

### 14.1 Tools

- **Ruff** — linting + import sorting + formatting (replaces Black, isort, flake8)
- **mypy** — static type checking, `--strict`
- **pytest** — test runner

### 14.2 Configuration in `pyproject.toml`

```toml
[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP", "N", "SIM", "RUF", "ASYNC", "S"]
ignore = ["E501"]  # Line length handled by formatter.

[tool.ruff.lint.per-file-ignores]
"tests/*" = ["S101"]  # asserts allowed in tests.

[tool.mypy]
strict = true
python_version = "3.11"
disallow_any_unimported = true
warn_unreachable = true
```

### 14.3 Pre-Commit Gate

`make check` runs locally before any commit:

```bash
ruff check . && ruff format --check . && mypy . && pytest -x
```

CI runs the same. A red CI blocks merge.

### 14.4 No Bikeshedding

Style decisions are delegated to Ruff. Do not argue about formatting in PRs — run the formatter.

---

## 15. Constants & Magic Values

### 15.1 No Magic Numbers in Logic

Every threshold, limit, timeout, model name, and prompt lives in a `constants.py` module within its owning package.

```python
# backend/app/rag/constants.py
SCOPE_REJECTION_SIMILARITY_THRESHOLD: float = 0.55
RETRIEVAL_TOP_K: int = 20
RETRIEVAL_FINAL_K: int = 5
GEMINI_GENERATION_MODEL: str = "gemini-1.5-flash"
GEMINI_EMBEDDING_MODEL: str = "text-embedding-004"
```

### 15.2 Prompts Are Constants

LLM prompts live in `backend/app/rag/prompts.py`, not inline:

```python
SYSTEM_PROMPT_TEMPLATE: str = """You are a legal research assistant for Indian criminal law,
specialized in robbery offences under the Bharatiya Nyaya Sanhita, 2023.

Answer using ONLY the provided sources. Cite using [1], [2] markers..."""
```

This makes prompt versioning, A/B testing, and diff review possible.

### 15.3 Corpus Version

`CORPUS_VERSION` is a single source of truth:

```python
# backend/app/constants.py
CORPUS_VERSION: str = "2026.05.01"
```

Cache entries store this. Index builder embeds this. Bumping it is a one-line change that invalidates all caches.

---

## 16. Common Anti-Patterns

A non-exhaustive list of things rejected in code review.

### 16.1 Direct SDK Imports in Business Logic

```python
# Rejected
from azure.cosmos import CosmosClient

async def store_query(query: str) -> None:
    client = CosmosClient.from_connection_string(...)
    ...
```

```python
# Correct
async def store_query(query: str, store: DocumentStore) -> None:
    await store.upsert(...)
```

### 16.2 Environment Variable Lookups Outside Config

```python
# Rejected
api_key = os.environ["GEMINI_API_KEY"]

# Correct
settings = get_settings()
api_key = settings.gemini_api_key.get_secret_value()
```

### 16.3 Bare Exception Catches

```python
# Rejected
try:
    result = await gemini.generate(prompt)
except:
    return None

# Correct
try:
    result = await gemini.generate(prompt)
except GeminiRateLimitError as e:
    await logger.awarning("gemini_rate_limited", retry_after=e.retry_after)
    raise CircuitBreakerOpen("LLM rate limited") from e
```

### 16.4 Untyped Dicts as Domain Objects

```python
# Rejected
def process_chunk(chunk: dict) -> dict:
    return {"text": chunk["text"], "score": chunk["score"]}

# Correct
def process_chunk(chunk: RetrievedChunk) -> ScoredChunk:
    return ScoredChunk(text=chunk.text, score=chunk.score)
```

### 16.5 Comments That Restate Code

```python
# Rejected
# Loop through chunks and add them to the result
for chunk in chunks:
    result.append(chunk)

# Correct — drop the comment, the code is the documentation
for chunk in chunks:
    result.append(chunk)
```

### 16.6 Global State

```python
# Rejected
_cache: dict[str, str] = {}

def get_cached(key: str) -> str | None:
    return _cache.get(key)

# Correct — inject the cache
class ExactCacheLookup:
    def __init__(self, store: DocumentStore) -> None:
        self._store = store
```

### 16.7 Hardcoded Local Paths

```python
# Rejected
db = sqlite3.connect("/home/me/projects/x/app.db")

# Correct
db = sqlite3.connect(settings.sqlite_path)
```

---

## 17. Library-Specific Notes

### 17.1 `dependency-injector` + FastAPI

The `@inject` decorator MUST be applied AFTER FastAPI's route decorator, and the `Provide[]` marker MUST be wrapped in `Depends()` (see §3.3 for rationale):

```python
@router.post("/query")        # First
@inject                        # Second
async def query_endpoint(
    request: QueryRequest,
    pipeline: Pipeline = Depends(Provide[Container.pipeline]),
) -> QueryResponse: ...
```

Wire the container in `main.py` before starting the app:

```python
container = Container()
container.config.from_pydantic(get_settings())
container.wire(modules=["backend.app.routes.query", "backend.app.routes.admin"])
```

### 17.2 `chromadb`

The Python client is synchronous as of writing. Always wrap calls in `asyncio.to_thread` when called from async code. Type stubs are incomplete — use `# type: ignore[import-untyped]` at the import.

### 17.3 `google-generativeai`

The official Gemini SDK has an async surface (`generate_content_async`). Always use it from FastAPI. Type stubs are incomplete — same ignore pattern as ChromaDB.

### 17.4 `azure-cosmos`

Use the **async** client `azure.cosmos.aio.CosmosClient`, not the sync `azure.cosmos.CosmosClient`. Returns `AsyncIterator` for queries.

### 17.5 `pydantic-settings`

Requires `pydantic >= 2.0` and a separate install (`pip install pydantic-settings`). It is not bundled with Pydantic 2.

### 17.6 `structlog`

Use `await logger.ainfo(...)` (async variants) inside async code. Configure once in `main.py`:

```python
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
)
```

### 17.7 `beautifulsoup4` (ingestion only)

Used in `ingestion/normalize/clean_html.py` to extract judgment text from Indian Kanoon HTML files. Use the `lxml` parser (`BeautifulSoup(html, "lxml")`) rather than the default `html.parser` — it is significantly faster and more lenient with malformed HTML, which Indian Kanoon occasionally produces. The judgment text on Indian Kanoon lives inside `<div class="judgments">`; everything else (navigation, ads, sidebar links) is stripped. Paragraph numbers in the source are preserved as `<p>` tags and should be carried forward into chunk metadata.

### 17.8 `pdfplumber` (ingestion only)

Used in `ingestion/normalize/parse_acts_pdf.py` to extract section text from indiacode.nic.in bare-act PDFs. Prefer `pdfplumber` over `pypdf` — it produces cleaner text on multi-column layouts and preserves whitespace meaningfully. Older IPC PDFs may contain scanned pages; if `page.extract_text()` returns empty for a page, log it and skip rather than failing the whole ingestion run. OCR is explicitly out of scope.

### 17.9 Gemini Relevance Classifier (ingestion only)

The relevance classifier (`ingestion/classify/relevance_classifier.py`) is a sync, offline-only Gemini call that filters bulk-downloaded judgments before indexing. It MUST request structured JSON output (use Gemini's `response_mime_type="application/json"` parameter) and validate the response with a Pydantic model `ClassifierVerdict(is_relevant: bool, relevance_score: float, reasoning: str)`. Never trust unvalidated LLM JSON. The prompt template lives in `ingestion/classify/prompts.py` as a module-level constant. Rate-limit local calls to respect the Gemini free tier (15 req/min) — use a simple `time.sleep(4)` between calls; this is offline batch work, latency is irrelevant.

---

## Quick Reference Card

When in doubt, ask:

1. Could a new contributor run this on their laptop with no Azure access?
2. Could I swap the cloud adapter for a local one with one config change?
3. Does this name explain itself, or do I need a comment to make it readable?
4. Does `mypy --strict` pass on this file?
5. Is every external dependency injected, or did I import a concrete SDK?
6. Is every threshold a named constant, or did I hardcode a number?
7. Did I catch a specific exception, or did I write `except:` / `except Exception:`?
8. Did I add structured logging with the required fields?

If any answer is "no", fix it before opening a PR.

---

_End of agent guide. Last updated: added guidance for offline ingestion pipeline — BeautifulSoup HTML parsing of Indian Kanoon judgments, pdfplumber for indiacode.nic.in bare-act PDFs, and a sync Gemini-based relevance classifier with structured JSON output validation. Update this file when conventions change — and update the code to match._
