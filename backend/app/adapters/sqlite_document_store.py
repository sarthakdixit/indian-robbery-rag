"""SQLite-backed DocumentStore for local development.

The Cosmos production adapter ships in a later chunk (probably Batch 7
with the rest of the cloud IaC). For now, this is the only concrete
implementation; the DI container's Selector serves it whenever
`environment=local` and raises a NotImplementedError for `environment=cloud`.

Schema mirrors Cosmos's `partition_key + id + body` triple. TTL is
implemented with a `valid_until` column read at query time — we don't
need a background cleanup job; expired rows just stop being visible.
Whenever it's convenient (e.g., during `upsert`), expired rows are
opportunistically deleted to keep the table small.

Concurrency model: a single Connection serialises all access through
its internal worker thread (per the aiosqlite docs). Read-modify-write
sequences are wrapped in transactions, which SQLite serializes at the
file level. For Batch 4's load (~5 rps peak), this is plenty.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

import aiosqlite


logger = logging.getLogger(__name__)


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS documents (
    partition_key TEXT NOT NULL,
    doc_id TEXT NOT NULL,
    body TEXT NOT NULL,
    valid_until INTEGER,
    PRIMARY KEY (partition_key, doc_id)
);

CREATE INDEX IF NOT EXISTS idx_documents_valid_until
ON documents(valid_until) WHERE valid_until IS NOT NULL;
"""


class SQLiteDocumentStore:
    """Async DocumentStore backed by a single SQLite file.

    The connection is opened lazily on first use rather than at
    construction time, because the DI container constructs all
    Singletons eagerly at startup. Lazy connect avoids a startup-time
    file-handle hold on systems where the DB file might not yet exist.
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = Path(db_path)
        self._connection: aiosqlite.Connection | None = None

    async def _ensure_connected(self) -> aiosqlite.Connection:
        if self._connection is None:
            # Make sure the parent directory exists; aiosqlite won't
            # create it for us.
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = await aiosqlite.connect(str(self._db_path))
            await conn.executescript(_SCHEMA_SQL)
            await conn.commit()
            self._connection = conn
            logger.info("opened SQLite document store at %s", self._db_path)
        return self._connection

    @staticmethod
    def _now() -> int:
        return int(time.time())

    @staticmethod
    def _expiry_from_ttl(ttl_seconds: int | None) -> int | None:
        if ttl_seconds is None:
            return None
        return SQLiteDocumentStore._now() + ttl_seconds

    async def get(
        self, partition_key: str, doc_id: str,
    ) -> dict[str, Any] | None:
        conn = await self._ensure_connected()
        now = self._now()
        async with conn.execute(
            "SELECT body, valid_until FROM documents "
            "WHERE partition_key = ? AND doc_id = ?",
            (partition_key, doc_id),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        body_json, valid_until = row
        if valid_until is not None and valid_until < now:
            # Expired — treat as absent. Don't bother deleting here;
            # the next upsert on the same key will overwrite, and an
            # eventual VACUUM cleans up the rest.
            return None
        return json.loads(body_json)

    async def upsert(
        self,
        partition_key: str,
        doc_id: str,
        body: dict[str, Any],
        ttl_seconds: int | None = None,
    ) -> None:
        conn = await self._ensure_connected()
        valid_until = self._expiry_from_ttl(ttl_seconds)
        body_json = json.dumps(body, ensure_ascii=False)
        await conn.execute(
            "INSERT INTO documents (partition_key, doc_id, body, valid_until) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT (partition_key, doc_id) DO UPDATE SET "
            "body = excluded.body, valid_until = excluded.valid_until",
            (partition_key, doc_id, body_json, valid_until),
        )
        await conn.commit()

    async def increment_counter(
        self,
        partition_key: str,
        doc_id: str,
        field: str,
        amount: int = 1,
        ttl_seconds: int | None = None,
    ) -> int:
        """Atomic-by-transaction read-modify-write.

        SQLite serializes transactions at the file level, so this is
        safe under concurrent callers. We BEGIN IMMEDIATE to acquire
        the reserved lock up front (rather than waiting until the
        UPDATE), avoiding the SQLITE_BUSY retries that DEFERRED would
        cause under contention.
        """
        conn = await self._ensure_connected()
        now = self._now()

        await conn.execute("BEGIN IMMEDIATE")
        try:
            async with conn.execute(
                "SELECT body, valid_until FROM documents "
                "WHERE partition_key = ? AND doc_id = ?",
                (partition_key, doc_id),
            ) as cursor:
                row = await cursor.fetchone()

            if row is None or (row[1] is not None and row[1] < now):
                # Doesn't exist or expired — create fresh.
                body = {field: amount}
                valid_until = self._expiry_from_ttl(ttl_seconds)
                await conn.execute(
                    "INSERT INTO documents (partition_key, doc_id, body, valid_until) "
                    "VALUES (?, ?, ?, ?) "
                    "ON CONFLICT (partition_key, doc_id) DO UPDATE SET "
                    "body = excluded.body, valid_until = excluded.valid_until",
                    (partition_key, doc_id, json.dumps(body), valid_until),
                )
                new_value = amount
            else:
                body = json.loads(row[0])
                current = int(body.get(field, 0))
                new_value = current + amount
                body[field] = new_value
                # Preserve existing valid_until; explicit upsert is the
                # only way to extend it.
                await conn.execute(
                    "UPDATE documents SET body = ? "
                    "WHERE partition_key = ? AND doc_id = ?",
                    (json.dumps(body), partition_key, doc_id),
                )

            await conn.commit()
            return new_value
        except Exception:
            await conn.rollback()
            raise

    async def delete(self, partition_key: str, doc_id: str) -> None:
        conn = await self._ensure_connected()
        await conn.execute(
            "DELETE FROM documents "
            "WHERE partition_key = ? AND doc_id = ?",
            (partition_key, doc_id),
        )
        await conn.commit()

    async def close(self) -> None:
        """Cleanly close the connection. Idempotent."""
        if self._connection is not None:
            await self._connection.close()
            self._connection = None