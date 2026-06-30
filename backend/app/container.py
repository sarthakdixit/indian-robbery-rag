"""Dependency-injection container.

Per AGENT.md §3, every cross-cutting dependency goes through this
container. Business logic depends on Protocols; the container picks
concrete adapters at startup based on `Settings.environment`.

The container is constructed once at process startup. CLI entry points
(`python -m backend.app.rag.pipeline`) and the FastAPI app (Batch 4)
both construct a Container, then resolve their root composite from it
(`container.pipeline()`).

Tests build their own container or override providers on this one — see
AGENT.md §11.3.
"""

from __future__ import annotations

from dependency_injector import containers, providers

from backend.app.adapters.sqlite_document_store import SQLiteDocumentStore
from backend.app.adapters.telemetry import AppInsightsTelemetry, StdoutTelemetry
from backend.app.adapters.turnstile import (
    AlwaysValidTurnstileVerifier,
    CloudflareTurnstileVerifier,
)
from backend.app.admin.aggregations import QueryLogAggregator
from backend.app.admin.auth import AdminAuth
from backend.app.cache.exact_cache import ExactAnswerCache, InMemoryExactCache
from backend.app.clients.gemini import (
    GeminiEmbeddingsAdapter,
    GeminiGenerationAdapter,
)
from backend.app.clients.stores import BM25SearchStore, ChromaVectorStore
from backend.app.config import CORPUS_VERSION, Settings, get_settings
from backend.app.protocols.document_store import DocumentStore
from backend.app.protocols.telemetry import TelemetryEmitter
from backend.app.protocols.turnstile import TurnstileVerifier
from backend.app.rag.generate import Generator
from backend.app.rag.pipeline import Pipeline
from backend.app.rag.retrieval import Retriever
from backend.app.security.circuit_breaker import CircuitBreaker
from backend.app.security.rate_limit import GlobalCap, RateLimiter
from backend.app.telemetry.query_log import QueryLogWriter


def _cosmos_document_store_factory(settings: Settings) -> DocumentStore:
    """Build CosmosDocumentStore from settings.

    The import is lazy so local-mode contributors don't need azure-cosmos
    installed to boot. The factory is only called when the DI Selector
    picks the `cloud` branch.
    """
    from backend.app.adapters.cosmos_document_store import CosmosDocumentStore

    return CosmosDocumentStore(
        connection_string=settings.cosmos_connection_string.get_secret_value(),
        database_name=settings.cosmos_database_name,
        container_name=settings.cosmos_container_name,
    )


def _cosmos_exact_cache_factory(store: DocumentStore) -> ExactAnswerCache:
    """Build CosmosExactCache wrapping the shared document_store.

    Like _cosmos_document_store_factory, the import is lazy so local-mode
    works without azure-cosmos installed.
    """
    from backend.app.adapters.cosmos_exact_cache import CosmosExactCache

    return CosmosExactCache(store=store)


class Container(containers.DeclarativeContainer):
    """Top-level DI container.

    All providers are wired declaratively. Each provider is one of:

      - `Singleton` — constructed once, reused for every resolution.
        Use for adapters holding connections, files, or in-memory state.
      - `Factory` — constructed each resolution. Use for lightweight
        composite objects that wrap Singletons.
      - `Selector` — picks one of several providers based on a key
        (here, `config.environment`). Use for local-vs-cloud swap.
      - `Callable` — wraps a plain function. Use for tiny helpers like
        extracting a field from another provider.
    """

    config: providers.Provider[Settings] = providers.Singleton(get_settings)

    corpus_version: providers.Provider[str] = providers.Object(CORPUS_VERSION)

    # --- Real-everywhere adapters ------------------------------------------
    embeddings_client = providers.Singleton(
        GeminiEmbeddingsAdapter,
        settings=config,
    )

    generation_client = providers.Singleton(
        GeminiGenerationAdapter,
        settings=config,
    )

    vector_store = providers.Singleton(
        ChromaVectorStore,
        settings=config,
    )

    bm25 = providers.Singleton(
        BM25SearchStore,
        settings=config,
    )

    # --- Local-vs-cloud selectable adapters --------------------------------
    # The Selector reads config.environment at resolution time. Tests can
    # override Settings.environment to "local" or "cloud" to exercise
    # either path.
    _environment = providers.Callable(lambda s: s.environment, config)

    document_store: providers.Provider[DocumentStore] = providers.Selector(
        _environment,
        local=providers.Singleton(
            SQLiteDocumentStore,
            db_path=providers.Callable(lambda s: s.sqlite_path, config),
        ),
        cloud=providers.Singleton(_cosmos_document_store_factory, settings=config),
    )

    exact_cache: providers.Provider[ExactAnswerCache] = providers.Selector(
        _environment,
        local=providers.Singleton(InMemoryExactCache),
        # CosmosExactCache wraps the shared document_store — it doesn't
        # open its own Cosmos connection. The factory pattern with lazy
        # import keeps local-mode boot free of azure-cosmos dependency.
        # Defined AFTER document_store because Python class-body scoping
        # requires forward references to be resolved at definition time.
        cloud=providers.Singleton(_cosmos_exact_cache_factory, store=document_store),
    )

    turnstile_verifier: providers.Provider[TurnstileVerifier] = providers.Selector(
        _environment,
        # AlwaysValid logs a WARNING on construction so a misconfigured
        # cloud deploy with environment=local is loud about it.
        local=providers.Singleton(AlwaysValidTurnstileVerifier),
        cloud=providers.Singleton(
            CloudflareTurnstileVerifier,
            settings=config,
        ),
    )

    # --- Security policies -------------------------------------------------
    # All three are constructed eagerly as Singletons so the route can
    # inject a long-lived reference. None of them holds external
    # connections (the document_store does); they are pure policy objects.
    rate_limiter = providers.Singleton(
        RateLimiter,
        store=document_store,
        daily_limit=providers.Callable(lambda s: s.per_ip_daily_query_limit, config),
    )

    global_cap = providers.Singleton(
        GlobalCap,
        store=document_store,
        daily_cap=providers.Callable(lambda s: s.global_daily_query_cap, config),
    )

    circuit_breaker = providers.Singleton(
        CircuitBreaker,
        daily_limit=providers.Callable(lambda s: s.local_llm_daily_limit, config),
    )

    # --- Telemetry ----------------------------------------------------------
    # `telemetry` is the structured-event sink (StdoutTelemetry locally,
    # AppInsightsTelemetry stub for cloud — real Azure wiring in Batch 7).
    # `query_log_writer` is the dashboard-data writer (Cosmos/SQLite via
    # the document_store).
    telemetry: providers.Provider[TelemetryEmitter] = providers.Selector(
        _environment,
        local=providers.Singleton(StdoutTelemetry),
        cloud=providers.Singleton(
            AppInsightsTelemetry,
            connection_string=providers.Callable(
                lambda s: s.app_insights_connection_string, config,
            ),
        ),
    )

    query_log_writer = providers.Singleton(
        QueryLogWriter,
        store=document_store,
    )

    # --- Admin dashboard ----------------------------------------------------
    # Both consumers of the query_log data the Batch 4.4 writer produces.
    # `admin_auth` is the password gate; `query_log_aggregator` does the
    # metric computations the admin endpoints surface.
    admin_auth = providers.Singleton(
        AdminAuth,
        settings=config,
    )

    query_log_aggregator = providers.Singleton(
        QueryLogAggregator,
        store=document_store,
    )

    # --- Pipeline composites -----------------------------------------------
    retriever = providers.Factory(
        Retriever,
        embeddings=embeddings_client,
        vector_store=vector_store,
        bm25=bm25,
    )

    generator = providers.Factory(
        Generator,
        generation_client=generation_client,
    )

    pipeline = providers.Factory(
        Pipeline,
        retriever=retriever,
        generator=generator,
        exact_cache=exact_cache,
        corpus_version=corpus_version,
    )