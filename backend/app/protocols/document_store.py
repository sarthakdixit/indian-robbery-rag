"""DocumentStore protocol — partition-keyed JSON document store.

The shape mirrors Cosmos DB's data model deliberately: every document
has a `partition_key`, a `doc_id`, and a JSON body. Cosmos uses these
exact terms; the SQLite local adapter (Batch 4.2 chunk) emulates them
with a composite primary key.

Per AGENT.md §2.3, the schema is intentionally identical so that the
local-vs-cloud adapter swap is a wiring change rather than a code
change. design.md §9 enumerates the document types we'll store
(rate_limit, query_log, cache_exact, cache_semantic, global_counter)
along with their partition keys; this Protocol doesn't enforce those
patterns — it only provides the primitives.

`increment_counter` is a specialised op because it must be atomic.
Cosmos has a native patch operation; SQLite uses a transaction. A
naive read-modify-write would race when two requests for the same
hashed_ip arrive concurrently. The Protocol commits all implementations
to atomicity at the (partition_key, doc_id, field) granularity.
"""

from __future__ import annotations

from typing import Any, Protocol


class DocumentStore(Protocol):
    """Async partition-keyed JSON document store.

    All methods are coroutine-safe — concurrent invocations from
    different async tasks must produce correct results without external
    locking by the caller. Cosmos achieves this via server-side ETags
    and patch ops; SQLite achieves it via per-connection serial
    transactions.
    """

    async def get(
        self, partition_key: str, doc_id: str,
    ) -> dict[str, Any] | None:
        """Return the body of the document, or None if not found.

        TTL-expired documents are treated as absent (return None).
        """
        ...

    async def upsert(
        self,
        partition_key: str,
        doc_id: str,
        body: dict[str, Any],
        ttl_seconds: int | None = None,
    ) -> None:
        """Create or replace a document.

        If `ttl_seconds` is set, the document expires after that many
        seconds from now. After expiry, `get` returns None and the
        document is eligible for cleanup by the adapter.

        TTL=None means the document never expires.
        """
        ...

    async def increment_counter(
        self,
        partition_key: str,
        doc_id: str,
        field: str,
        amount: int = 1,
        ttl_seconds: int | None = None,
    ) -> int:
        """Atomically add `amount` to `body[field]` and return the new value.

        If the document doesn't exist, it's created with `body[field] =
        amount`. If the field doesn't exist on an existing document, it's
        initialized to `amount`. Other fields on the document are
        preserved.

        `ttl_seconds` applies only on creation (or refresh, in the case
        of TTL-expired documents being re-created). It does NOT bump the
        TTL of an existing live document — explicit upsert is required
        for that.
        """
        ...

    async def delete(self, partition_key: str, doc_id: str) -> None:
        """Remove a document. No-op if it doesn't exist."""
        ...

    async def list_by_partition(
        self, partition_key: str, limit: int = 1000,
    ) -> list[dict[str, Any]]:
        """Return all live (non-expired) document bodies in the given partition.

        Returned in unspecified order — callers that need a particular
        ordering (e.g., recent-first by timestamp) must sort the result
        themselves. This keeps the Protocol portable across stores with
        different native ordering semantics (Cosmos vs SQLite vs Redis).

        `limit` caps the number of documents returned. For the admin
        dashboard's per-day partitions (~200 docs/day max), the default
        of 1000 is comfortably above any realistic load. Documents
        beyond the limit are silently truncated; if pagination matters
        for a future use case, extend this signature.

        Returns an empty list (NOT None) when the partition has no
        documents — partitions don't "exist" as first-class objects in
        Cosmos's data model and the adapter shouldn't pretend otherwise.
        """
        ...