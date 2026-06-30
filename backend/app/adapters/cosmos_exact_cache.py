"""Cloud-mode exact cache backed by Cosmos via the DocumentStore protocol.

This is intentionally NOT a separate Cosmos client — it sits on top of
the shared `DocumentStore` so the DI container can wire it up with the
same Cosmos connection used for rate limits and query logs. design.md
§9 puts all cache entries in the same Cosmos container, partition
`"cache:exact"`, keyed by the SHA-256 of the normalized query.

The CachedAnswer dataclass is serialized to a dict for storage and
re-hydrated on read.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import asdict
from typing import Any

from backend.app.cache.exact_cache import CachedAnswer, normalize_query
from backend.app.protocols.document_store import DocumentStore


logger = logging.getLogger(__name__)

# Partition key for all exact-cache entries per design.md §9.
_PARTITION_KEY: str = "cache:exact"


class CosmosExactCache:
    """ExactAnswerCache implementation backed by a DocumentStore.

    Despite the name, this class doesn't import azure-cosmos — it works
    against the DocumentStore abstraction. In cloud mode, the wired
    DocumentStore is CosmosDocumentStore; in local-with-persistence
    mode, it could just as well be SQLiteDocumentStore. The name
    captures the production deployment target, not the technical
    coupling.
    """

    def __init__(self, store: DocumentStore) -> None:
        self._store = store

    @staticmethod
    def _doc_id_for(query: str) -> str:
        """Hash the normalized query to produce a Cosmos doc id.

        SHA-256 hex is 64 chars, well under Cosmos's 255-char id limit,
        and is collision-resistant for our scale (a SHA-256 collision
        would be unprecedented). Hashing also means the doc id doesn't
        embed raw user input, which is nice for logging.
        """
        normalized = normalize_query(query)
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    async def get(
        self, query: str, *, current_corpus_version: str,
    ) -> CachedAnswer | None:
        doc_id = self._doc_id_for(query)
        body = await self._store.get(_PARTITION_KEY, doc_id)
        if body is None:
            return None
        # Corpus-version check happens here (not at write time) so an
        # entry written under v1 becomes invisible when the app boots
        # against v2, without needing a sweeper job.
        if body.get("corpus_version") != current_corpus_version:
            return None
        try:
            return CachedAnswer(
                answer_text=body["answer_text"],
                used_chunk_ids=list(body.get("used_chunk_ids", [])),
                used_chunk_metadata=list(body.get("used_chunk_metadata", [])),
                used_chunk_texts=list(body.get("used_chunk_texts", [])),
                corpus_version=body.get("corpus_version", ""),
                model=body.get("model", ""),
            )
        except KeyError as e:
            # Schema drift between versions — treat as miss rather than
            # error out. Logged so we notice if it happens frequently.
            logger.warning("exact cache schema mismatch: missing key %s", e)
            return None

    async def put(self, query: str, entry: CachedAnswer) -> None:
        doc_id = self._doc_id_for(query)
        body: dict[str, Any] = asdict(entry)
        # No TTL — cache entries live until invalidated by a corpus
        # version bump (handled at read time).
        await self._store.upsert(_PARTITION_KEY, doc_id, body)