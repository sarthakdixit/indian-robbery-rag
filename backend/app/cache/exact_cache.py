"""Exact-match answer cache.

A simple key-value store keyed on a normalized form of the user's query.
Used as the first cache lookup in the pipeline before paying the cost of
embedding + retrieval + generation.

Three implementations are planned:

  - `InMemoryExactCache` (this chunk) — dict-backed, no persistence.
    Lost on process restart. Fine for local dev and the Batch 3
    verification CLI; cheap and dependency-free.
  - `SQLiteExactCache` (deferred to Batch 4) — sqlite-backed, persists
    across restarts. Drop-in replacement for local production.
  - `CosmosExactCache` (deferred to Batch 4) — Cosmos-backed, the
    cloud production target.

All three implement the same `ExactAnswerCache` Protocol so the DI
container can swap between them based on `Settings.environment`.

Normalization rules (intentionally aggressive — we want "What is robbery"
and "what  is robbery?" to hit the same cache entry):
  - Lowercase
  - Strip leading/trailing whitespace
  - Collapse internal whitespace runs to single spaces
  - Strip trailing punctuation (`. ! ? , ; :`)

Each cache entry carries the corpus_version it was generated against.
On lookup, entries with a different corpus_version are treated as misses
(see AGENT.md §15.3 — bumping CORPUS_VERSION invalidates the cache).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Protocol


# Trailing punctuation to strip — sentence-final marks only. Apostrophes
# and other in-word punctuation are preserved (e.g., "what's robbery"
# should not become "what s robbery").
_TRAILING_PUNCT_RE = re.compile(r"[.!?,;:]+$")
_WHITESPACE_RE = re.compile(r"\s+")


def normalize_query(query: str) -> str:
    """Normalize a query for exact-cache lookup.

    Two queries that produce the same normalized form are treated as
    cache-equivalent. The function is intentionally lossy — preserving
    capitalization or extra whitespace would defeat exact matching.
    """
    out = query.lower().strip()
    out = _WHITESPACE_RE.sub(" ", out)
    out = _TRAILING_PUNCT_RE.sub("", out)
    return out


@dataclass(frozen=True)
class CachedAnswer:
    """A cache entry. Stores enough to reconstruct a `PipelineResponse`
    without re-running retrieval or generation."""

    answer_text: str
    used_chunk_ids: list[str]
    used_chunk_metadata: list[dict[str, Any]] = field(default_factory=list)
    used_chunk_texts: list[str] = field(default_factory=list)
    corpus_version: str = ""
    model: str = ""


class ExactAnswerCache(Protocol):
    """Async exact-match cache.

    Implementations must:
      - Treat entries whose corpus_version doesn't match the current one
        as misses (i.e., return None).
      - Be safe to call from multiple coroutines concurrently.
    """

    async def get(self, query: str, *, current_corpus_version: str) -> CachedAnswer | None: ...
    async def put(self, query: str, entry: CachedAnswer) -> None: ...


class InMemoryExactCache:
    """Dict-backed cache. No persistence.

    Suitable for the Batch 3 verification CLI and unit tests. Production
    swaps to SQLite or Cosmos via the DI container.

    Concurrency: a single asyncio event loop runs callbacks serially
    between await points, so dict mutations don't need locks. If we
    ever move to multi-threaded execution, this needs revisiting.
    """

    def __init__(self) -> None:
        self._store: dict[str, CachedAnswer] = {}

    async def get(
        self, query: str, *, current_corpus_version: str,
    ) -> CachedAnswer | None:
        key = normalize_query(query)
        entry = self._store.get(key)
        if entry is None:
            return None
        if entry.corpus_version != current_corpus_version:
            # Don't proactively evict — a later put will overwrite. This
            # avoids surprising mutation during a read.
            return None
        return entry

    async def put(self, query: str, entry: CachedAnswer) -> None:
        key = normalize_query(query)
        self._store[key] = entry

    def size(self) -> int:
        """Diagnostic — number of entries (not part of the Protocol)."""
        return len(self._store)