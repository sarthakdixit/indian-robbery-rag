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

from backend.app.cache.exact_cache import ExactAnswerCache, InMemoryExactCache
from backend.app.clients.gemini import (
    GeminiEmbeddingsAdapter,
    GeminiGenerationAdapter,
)
from backend.app.clients.stores import BM25SearchStore, ChromaVectorStore
from backend.app.config import CORPUS_VERSION, Settings, get_settings
from backend.app.rag.generate import Generator
from backend.app.rag.pipeline import Pipeline
from backend.app.rag.retrieval import Retriever


def _cloud_exact_cache_placeholder() -> ExactAnswerCache:
    """Stub for the cloud exact-cache provider.

    Raises rather than silently falling back so a misconfigured cloud
    deploy fails loudly. Replaced with `CosmosExactCache` in Batch 4.
    """
    raise NotImplementedError(
        "Cloud exact cache (CosmosExactCache) not yet implemented; "
        "ships with Batch 4 once the document store lands."
    )


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

    exact_cache: providers.Provider[ExactAnswerCache] = providers.Selector(
        _environment,
        local=providers.Singleton(InMemoryExactCache),
        cloud=providers.Singleton(_cloud_exact_cache_placeholder),
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