"""HTTP-layer smoke tests.

These verify the FastAPI app, middleware, security checks, and admin
endpoints are correctly wired — NOT the business logic of the pipeline
itself (that's in unit tests).

Design choice: we override the `pipeline` provider with a deterministic
stub instead of mocking Gemini / ChromaDB / BM25 individually. This:
  - Runs in milliseconds (no embedding API call, no vector search)
  - Costs nothing (no Gemini quota burn)
  - Tests the actual route handlers, validation, and middleware
  - Doesn't test retrieval quality — that's the eval set's job (Batch 8)

The stub returns canned PipelineSuccess for "robbery"-keyword queries
and PipelineOutOfScope for everything else, mimicking the production
scope check.

Run with: pytest backend/tests/test_smoke.py -v
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from dependency_injector import providers
from fastapi.testclient import TestClient

from backend.app.rag.pipeline import (
    CitationCard,
    PipelineOutOfScope,
    PipelineResponse,
    PipelineSuccess,
)


# ---------------------------------------------------------------------
# Stub pipeline
# ---------------------------------------------------------------------

class StubPipeline:
    """Deterministic stand-in for the real Pipeline.

    Returns a fixed PipelineSuccess for queries containing "robbery"
    (case-insensitive); PipelineOutOfScope for anything else. No
    retrieval, no Gemini, no embedding. ~1ms per call.
    """

    def __init__(self) -> None:
        self._call_count = 0

    async def answer(
        self, query: str, *, request_id: str | None = None,
    ) -> PipelineResponse:
        self._call_count += 1
        rid = request_id or f"stub-rid-{self._call_count}"

        if "robbery" in query.lower():
            return PipelineSuccess(
                answer="Robbery is theft or extortion with force [1].",
                citations=[
                    CitationCard(
                        index=1,
                        source_type="act",
                        citation="BNS §309",
                        excerpt="Robbery — theft is robbery if...",
                        source_url="https://example.test/bns309",
                        pdf_url=None,
                        court=None,
                        year=None,
                        metadata={"section_number": "309", "act_id": "bns_2023"},
                    ),
                ],
                request_id=rid,
                cache_hit=False,
                latency_ms=42.0,
                prompt_tokens=100,
                output_tokens=50,
            )
        return PipelineOutOfScope(
            request_id=rid,
            latency_ms=12.0,
            suggestions=[
                "What is robbery under BNS?",
                "Difference between robbery and theft?",
                "Punishment for dacoity?",
            ],
        )


# ---------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------

@pytest.fixture
def temp_sqlite_path(tmp_path: Path) -> Path:
    """A fresh SQLite path per test. tmp_path is a pytest builtin."""
    return tmp_path / "test_app.db"


@pytest.fixture
def admin_password() -> str:
    return "test-admin-password-do-not-use-in-prod"


@pytest.fixture
def stub_pipeline() -> StubPipeline:
    return StubPipeline()


@pytest.fixture
def app_with_stub(
    monkeypatch: pytest.MonkeyPatch,
    temp_sqlite_path: Path,
    admin_password: str,
    stub_pipeline: StubPipeline,
) -> Any:
    """Build the FastAPI app with stubbed pipeline + isolated state.

    Cross-test contamination guards (this is the tricky bit):

    Python caches imported modules. The first test imports `backend.app.main`,
    which constructs the DI container ONCE with the first test's Settings.
    Subsequent tests get the same container, same singletons, same in-memory
    state. Even though we set SQLITE_PATH per-test, it has no effect because
    Settings was already cached.

    The fix: override every stateful singleton with a fresh instance pointing
    at the per-test paths. The container itself is shared (cheap; just a
    registry) but each provider returns a brand-new object for the duration
    of one test.

    Overrides:
      pipeline       — StubPipeline (replaces real Gemini/retrieval)
      document_store — fresh SQLite at tmp_path (resets rate limit + logs)
      exact_cache    — fresh InMemoryExactCache (no cached answers)
    """
    # Settings env is set first, primarily so the first-test import has
    # something valid. Subsequent tests' values are read by Settings only
    # if @lru_cache is reset — but we don't rely on that.
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-do-not-call-gemini")
    monkeypatch.setenv("ENVIRONMENT", "local")
    monkeypatch.setenv("ADMIN_PASSWORD", admin_password)
    monkeypatch.setenv("IP_HASH_SALT", "test-salt-12345")

    # Import after env is set. If main was already imported in a previous
    # test, this is a no-op (Python returns the cached module).
    from backend.app.adapters.sqlite_document_store import SQLiteDocumentStore
    from backend.app.cache.exact_cache import InMemoryExactCache
    from backend.app.main import app, container

    # Build the per-test stateful singletons. Each is a fresh object.
    fresh_store = SQLiteDocumentStore(db_path=temp_sqlite_path)
    fresh_cache = InMemoryExactCache()

    # Override each provider. dependency-injector accepts a provider
    # object on the LHS and a Provider-wrapped value on the RHS;
    # `providers.Object` wraps an existing instance so the container
    # returns it as-is rather than constructing something new.
    container.pipeline.override(providers.Object(stub_pipeline))
    container.document_store.override(providers.Object(fresh_store))
    container.exact_cache.override(providers.Object(fresh_cache))

    # Also override admin_password — it was baked into AdminAuth at
    # container-build time and won't pick up our monkeypatched env.
    # We rebuild AdminAuth with a Settings instance that has our
    # per-test password.
    from backend.app.admin.auth import AdminAuth
    from backend.app.config import Settings
    from pydantic import SecretStr

    test_settings = Settings(
        gemini_api_key=SecretStr("test-key"),  # type: ignore[call-arg]
        admin_password=SecretStr(admin_password),
        ip_hash_salt=SecretStr("test-salt-12345"),
    )
    container.admin_auth.override(providers.Object(AdminAuth(test_settings)))

    # Critical: reset every cached singleton so transitive consumers of
    # document_store (rate_limiter, global_cap, query_log_aggregator,
    # query_log_writer) rebuild against the OVERRIDDEN document_store
    # instead of holding references to the previous test's store.
    # Without this, providers like query_log_aggregator continue using
    # whichever document_store they were FIRST built with, and overrides
    # only affect direct lookups (not transitively-resolved deps).
    container.reset_singletons()

    yield app

    # Tear down — reset all overrides so the next test starts clean.
    # `reset_singletons` here too so the next test's reset_override+
    # reset_singletons cycle starts from a clean slate.
    container.pipeline.reset_override()
    container.document_store.reset_override()
    container.exact_cache.reset_override()
    container.admin_auth.reset_override()
    container.reset_singletons()


@pytest.fixture
def client(app_with_stub: Any) -> TestClient:
    return TestClient(app_with_stub)


# ---------------------------------------------------------------------
# Tests — basic liveness
# ---------------------------------------------------------------------

def test_health_endpoint_returns_ok(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "uptime_seconds" in body


def test_health_response_has_request_id_header(client: TestClient) -> None:
    response = client.get("/api/health")
    assert "x-request-id" in response.headers


# ---------------------------------------------------------------------
# Tests — query endpoint
# ---------------------------------------------------------------------

def test_query_happy_path_returns_answer_and_citations(client: TestClient) -> None:
    response = client.post(
        "/api/query",
        json={"question": "What is robbery?", "turnstile_token": "test-token"},
    )
    assert response.status_code == 200
    body = response.json()
    assert "answer" in body
    assert "citations" in body
    assert body["cache_hit"] is False
    assert len(body["citations"]) == 1
    assert body["citations"][0]["citation"] == "BNS §309"


def test_query_excludes_token_fields_from_response(client: TestClient) -> None:
    """prompt_tokens and output_tokens are internal; never leak in HTTP response."""
    response = client.post(
        "/api/query",
        json={"question": "What is robbery?", "turnstile_token": "test-token"},
    )
    assert response.status_code == 200
    body = response.json()
    assert "prompt_tokens" not in body
    assert "output_tokens" not in body


def test_query_out_of_scope_returns_suggestions(client: TestClient) -> None:
    response = client.post(
        "/api/query",
        json={"question": "How do I bake cookies?", "turnstile_token": "test-token"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body.get("error_code") == "out_of_scope"
    assert "suggestions" in body
    assert len(body["suggestions"]) >= 1


def test_query_validates_missing_turnstile_token(client: TestClient) -> None:
    response = client.post("/api/query", json={"question": "robbery"})
    assert response.status_code == 422


def test_query_validates_question_too_short(client: TestClient) -> None:
    response = client.post(
        "/api/query",
        json={"question": "a", "turnstile_token": "test-token"},
    )
    assert response.status_code == 422


def test_query_rejects_extra_fields(client: TestClient) -> None:
    response = client.post(
        "/api/query",
        json={
            "question": "robbery",
            "turnstile_token": "test-token",
            "extra_param": "not allowed",
        },
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------
# Tests — rate limiting
# ---------------------------------------------------------------------

def test_rate_limit_triggers_after_threshold(client: TestClient) -> None:
    """5 in-scope queries succeed, 6th returns 429."""
    for i in range(5):
        response = client.post(
            "/api/query",
            json={"question": "robbery query #{i}", "turnstile_token": "t"},
        )
        assert response.status_code == 200, f"query {i+1} failed: {response.json()}"

    response = client.post(
        "/api/query",
        json={"question": "robbery query 6", "turnstile_token": "t"},
    )
    assert response.status_code == 429
    body = response.json()
    assert body["error_code"] == "rate_limit_exceeded"


def test_oos_does_not_consume_rate_limit(client: TestClient) -> None:
    """OOS rejections don't count toward the per-IP rate limit (FR-3)."""
    # Burn 4 OOS queries — none should consume the rate limit budget.
    for _ in range(4):
        response = client.post(
            "/api/query",
            json={"question": "cookies recipe", "turnstile_token": "t"},
        )
        assert response.status_code == 200
        assert response.json().get("error_code") == "out_of_scope"

    # Now do 5 in-scope queries — all should succeed.
    for i in range(5):
        response = client.post(
            "/api/query",
            json={"question": f"robbery query #{i}", "turnstile_token": "t"},
        )
        assert response.status_code == 200, (
            f"in-scope query {i+1} unexpectedly failed: {response.json()}"
        )


# ---------------------------------------------------------------------
# Tests — admin endpoints
# ---------------------------------------------------------------------

def test_admin_summary_rejects_missing_password(client: TestClient) -> None:
    response = client.get("/api/admin/summary")
    assert response.status_code == 401
    assert response.json()["error_code"] == "admin_auth_failed"


def test_admin_summary_rejects_wrong_password(client: TestClient) -> None:
    response = client.get(
        "/api/admin/summary",
        headers={"x-admin-password": "wrong"},
    )
    assert response.status_code == 401


def test_admin_summary_with_no_data_returns_zeros(
    client: TestClient, admin_password: str,
) -> None:
    """Empty SQLite → /summary returns all-zero counts (not 500)."""
    response = client.get(
        "/api/admin/summary",
        headers={"x-admin-password": admin_password},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total_queries"] == 0
    assert body["total_successes"] == 0
    assert body["total_rejections"] == 0
    assert body["rejection_rate"] == 0.0
    # 7-day default window
    assert len(body["daily"]) == 7


def test_admin_summary_after_queries_shows_counts(
    client: TestClient, admin_password: str,
) -> None:
    """Run 2 queries (one in-scope, one OOS), then verify /summary aggregates."""
    client.post("/api/query", json={"question": "robbery", "turnstile_token": "t"})
    client.post("/api/query", json={"question": "cookies", "turnstile_token": "t"})

    response = client.get(
        "/api/admin/summary",
        headers={"x-admin-password": admin_password},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total_queries"] == 2
    assert body["total_successes"] == 1
    assert body["total_rejections"] == 1


def test_admin_top_questions_lists_asked(
    client: TestClient, admin_password: str,
) -> None:
    """After 3 queries with 2 distinct questions, /top-questions reflects counts."""
    for _ in range(2):
        client.post(
            "/api/query",
            json={"question": "What is robbery?", "turnstile_token": "t"},
        )
    client.post(
        "/api/query",
        json={"question": "Robbery sentencing?", "turnstile_token": "t"},
    )

    response = client.get(
        "/api/admin/top-questions",
        headers={"x-admin-password": admin_password},
    )
    assert response.status_code == 200
    items = response.json()["items"]
    # 2 distinct questions; first one (asked twice) is on top
    assert items[0]["count"] == 2
    assert items[0]["question"] == "What is robbery?"


def test_admin_recent_queries_pagination(
    client: TestClient, admin_password: str,
) -> None:
    """Make 3 queries, then page through /recent-queries with limit=2."""
    for i in range(3):
        client.post(
            "/api/query",
            json={"question": f"robbery #{i}", "turnstile_token": "t"},
        )

    response = client.get(
        "/api/admin/recent-queries?limit=2&offset=0",
        headers={"x-admin-password": admin_password},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert body["limit"] == 2
    assert body["offset"] == 0
    assert len(body["items"]) == 2
    # hashed_ip is truncated for display
    assert all(len(item["hashed_ip_short"]) <= 12 for item in body["items"])


def test_admin_summary_rejects_inverted_date_range(
    client: TestClient, admin_password: str,
) -> None:
    response = client.get(
        "/api/admin/summary?start_date=2026-06-20&end_date=2026-06-01",
        headers={"x-admin-password": admin_password},
    )
    assert response.status_code == 400
    assert response.json()["error_code"] == "invalid_query"


def test_admin_summary_rejects_oversized_window(
    client: TestClient, admin_password: str,
) -> None:
    """Pydantic Query(le=90) rejects days > 90 with 422."""
    response = client.get(
        "/api/admin/summary?days=365",
        headers={"x-admin-password": admin_password},
    )
    assert response.status_code == 422