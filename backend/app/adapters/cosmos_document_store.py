"""Cosmos DB DocumentStore — production adapter.

Mirrors the contract of SQLiteDocumentStore (backend/app/adapters/
sqlite_document_store.py). See backend/app/protocols/document_store.py
for the full method contract.

## Document layout

Cosmos items are flat JSON. We store the protocol's `body` dict under a
nested "body" key rather than flattening it onto the item, so that field
names inside body cannot collide with Cosmos reserved names ("id", "pk",
"_ts", "_etag", "_rid", "_self", "_attachments"). A stored item looks
like:

    {
      "id":   "<doc_id>",
      "pk":   "<partition_key>",
      "body": { ... user-provided body ... },
      "ttl":  <seconds-from-now-int>  or  -1  for never expire,
      "_ts":  <unix-timestamp-set-by-cosmos>,
      ...    <other cosmos-reserved fields>
    }

`get` extracts and returns just `body`. `increment_counter` patches the
nested path `/body/{field}` using Cosmos's native `incr` patch op,
which is atomic at the server.

## TTL

Cosmos has built-in document TTL. The container must be created with
`defaultTtl=-1` (TTL enabled but not auto-applied). Per-document TTL
is set via the `ttl` field on the item — positive integer means
expiration in that many seconds from now (re-applied each write).
TTL=None in the protocol maps to NOT setting the field at all
(equivalent to "never expire").

## Concurrency model

Cosmos is fundamentally distributed; concurrency safety comes from
server-side patch operations being atomic per-item. Our
`increment_counter` uses `patch_item` with `{"op": "incr", "path":
"/body/<field>", "value": amount}` which the server applies under
lock. If the item doesn't exist yet, patch raises 404 — we catch
and fall back to `upsert_item`. Two concurrent first-write requests
can race here (both see 404, both upsert), but `upsert_item` is
last-write-wins, and the next `increment_counter` will patch
correctly. Worst case: one increment is lost on the very first
write. Acceptable for rate-limit counters.

## Connection lifecycle

Like SQLiteDocumentStore, the client is opened lazily on first use.
The DI container constructs singletons eagerly; lazy connect avoids
holding network connections during startup before they're needed.
"""

from __future__ import annotations

import logging
from typing import Any

# Azure SDK types — using the async client per AGENT.md §17.4.
# `# type: ignore[import-untyped]` because azure-cosmos doesn't ship
# fully-resolved stubs as of the project's pinned version.
from azure.cosmos import exceptions  # type: ignore[import-untyped]
from azure.cosmos.aio import CosmosClient, ContainerProxy  # type: ignore[import-untyped]


logger = logging.getLogger(__name__)


class CosmosDocumentStore:
    """Async DocumentStore backed by Azure Cosmos DB.

    Construction is cheap — the SDK client doesn't open any network
    connection until the first request. `close` should be called at
    application shutdown to release the underlying HTTP session.
    """

    def __init__(
        self,
        connection_string: str,
        database_name: str,
        container_name: str,
    ) -> None:
        self._connection_string = connection_string
        self._database_name = database_name
        self._container_name = container_name
        self._client: CosmosClient | None = None
        self._container: ContainerProxy | None = None

    # -----------------------------------------------------------------
    # Connection management
    # -----------------------------------------------------------------

    async def _ensure_connected(self) -> ContainerProxy:
        if self._container is not None:
            return self._container
        # Lazy-create the client. The CosmosClient takes a connection
        # string OR (endpoint, credential) pair. We use the connection
        # string form here for compatibility with how Key Vault stores
        # the secret. Switching to managed identity is a Batch 7 task.
        self._client = CosmosClient.from_connection_string(self._connection_string)
        database = self._client.get_database_client(self._database_name)
        self._container = database.get_container_client(self._container_name)
        logger.info(
            "opened Cosmos document store: db=%s container=%s",
            self._database_name, self._container_name,
        )
        return self._container

    async def close(self) -> None:
        """Release the underlying HTTP session. Idempotent."""
        if self._client is not None:
            await self._client.close()
            self._client = None
            self._container = None

    # -----------------------------------------------------------------
    # Protocol methods
    # -----------------------------------------------------------------

    async def get(
        self, partition_key: str, doc_id: str,
    ) -> dict[str, Any] | None:
        """Return the body of the document, or None if not found or TTL-expired.

        Cosmos handles TTL transparently — expired documents return 404,
        same as never-existed. We don't have to filter explicitly.
        """
        container = await self._ensure_connected()
        try:
            item = await container.read_item(item=doc_id, partition_key=partition_key)
        except exceptions.CosmosResourceNotFoundError:
            return None
        # `body` is the nested dict we stored; cast for mypy strict.
        body = item.get("body")
        if not isinstance(body, dict):
            # Shouldn't happen with our writes, but be defensive against
            # documents written by older code paths.
            return None
        return body

    async def upsert(
        self,
        partition_key: str,
        doc_id: str,
        body: dict[str, Any],
        ttl_seconds: int | None = None,
    ) -> None:
        """Create or replace a document with optional TTL."""
        container = await self._ensure_connected()
        item: dict[str, Any] = {
            "id": doc_id,
            "pk": partition_key,
            "body": body,
        }
        if ttl_seconds is not None:
            item["ttl"] = int(ttl_seconds)
        await container.upsert_item(body=item)

    async def increment_counter(
        self,
        partition_key: str,
        doc_id: str,
        field: str,
        amount: int = 1,
        ttl_seconds: int | None = None,
    ) -> int:
        """Atomic increment via Cosmos server-side patch.

        Falls back to upsert if the document doesn't exist yet. The
        very-first-write race is documented in the module docstring.
        """
        container = await self._ensure_connected()
        path = f"/body/{field}"
        try:
            response = await container.patch_item(
                item=doc_id,
                partition_key=partition_key,
                patch_operations=[
                    {"op": "incr", "path": path, "value": amount},
                ],
            )
            # The patched item is returned; extract the new counter value.
            body = response.get("body", {})
            new_value = body.get(field, amount)
            if not isinstance(new_value, int):
                # Shouldn't happen — Cosmos `incr` is type-checked server-side
                # against the existing field. Be defensive anyway.
                return int(new_value)
            return new_value
        except exceptions.CosmosResourceNotFoundError:
            # First write — patch can't create. Fall back to upsert.
            await self.upsert(
                partition_key=partition_key,
                doc_id=doc_id,
                body={field: amount},
                ttl_seconds=ttl_seconds,
            )
            return amount
        except exceptions.CosmosHttpResponseError as e:
            # 412 (precondition failed) and other patch failures —
            # surface with context for debugging.
            logger.warning(
                "patch_item failed: pk=%s id=%s field=%s status=%s msg=%s",
                partition_key, doc_id, field, e.status_code, e,
            )
            raise

    async def delete(self, partition_key: str, doc_id: str) -> None:
        """Delete a document. No-op if it doesn't exist."""
        container = await self._ensure_connected()
        try:
            await container.delete_item(item=doc_id, partition_key=partition_key)
        except exceptions.CosmosResourceNotFoundError:
            return

    async def list_by_partition(
        self, partition_key: str, limit: int = 1000,
    ) -> list[dict[str, Any]]:
        """Return all live document bodies in the partition, up to `limit`.

        Uses a parameterized query restricted to the partition (cross-
        partition queries are expensive). Cosmos's `query_items` returns
        an async iterator; we materialize up to `limit` items.

        Returned in unspecified order (Cosmos's natural order is roughly
        insertion-time within a partition, but the protocol doesn't
        promise this).
        """
        container = await self._ensure_connected()
        results: list[dict[str, Any]] = []
        # `partition_key=` scopes the query to one logical partition,
        # avoiding fan-out across the cluster. Much cheaper than
        # enable_cross_partition_query=True.
        query_iter = container.query_items(
            query="SELECT TOP @limit * FROM c WHERE c.pk = @pk",
            parameters=[
                {"name": "@pk", "value": partition_key},
                {"name": "@limit", "value": limit},
            ],
            partition_key=partition_key,
        )
        async for item in query_iter:
            body = item.get("body")
            if isinstance(body, dict):
                results.append(body)
            if len(results) >= limit:
                break
        return results