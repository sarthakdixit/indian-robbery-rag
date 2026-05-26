"""Retrieval-store adapters.

Both ChromaDB and bm25s expose synchronous Python APIs. Per AGENT.md §7.3
and §17.2, we wrap them in `asyncio.to_thread` so they can be awaited from
FastAPI routes without blocking the event loop.

`ChromaVectorStore`:
  - Opens the collection at process startup, holds a reference for the
    lifetime of the process. Re-opening per request is wasteful and
    would defeat ChromaDB's internal connection pooling.
  - Translates ChromaDB's cosine-distance score (1 - cosine_sim) back to
    cosine similarity in [0, 1] so callers can reason about similarities
    without thinking about which side is "better."

`BM25SearchStore`:
  - Loads the bm25s index and the parallel chunk_ids file at startup.
  - The tokenizer is intentionally duplicated from the ingestion-time
    builder (`ingestion/index/build_bm25.py`). Importing from ingestion
    would couple the runtime backend to the offline ingestion package,
    which is the wrong dependency direction. Keep the tokenizer in sync
    by hand if either side ever changes.
  - Loads chunks.jsonl once at startup so we can return chunk text +
    metadata alongside scores. The chunks file is ~5-10MB for our corpus
    — fine to hold in memory.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

import chromadb  # type: ignore[import-untyped]
from chromadb.config import Settings as ChromaSettings  # type: ignore[import-untyped]
import bm25s  # type: ignore[import-untyped]

from backend.app.protocols.retrieval import RetrievedChunk

if TYPE_CHECKING:
    from backend.app.config import Settings


logger = logging.getLogger(__name__)


# --- BM25 tokenizer (mirror of ingestion/index/build_bm25.py) -------------
# Keep this in sync with the ingestion-time tokenizer. A mismatch produces
# silently degraded keyword retrieval: query tokens never match indexed
# tokens. Test coverage in Batch 8 will catch obvious drift.
_TOKEN_SPLIT_RE = re.compile(r"[^a-z0-9_]+")
_MIN_TOKEN_LEN: int = 2


def _tokenize(text: str) -> list[str]:
    lowered = text.lower().replace("§", "section ")
    raw_tokens = _TOKEN_SPLIT_RE.split(lowered)
    return [tok for tok in raw_tokens if len(tok) >= _MIN_TOKEN_LEN]


class ChromaVectorStore:
    """Async wrapper around a ChromaDB persistent collection."""

    def __init__(self, settings: Settings) -> None:
        self._collection_name = settings.chroma_collection_name
        client = chromadb.PersistentClient(
            path=str(settings.chroma_db_dir),
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        # `get_collection` (not `get_or_create_collection`) — we expect
        # ingestion to have built it. If it's missing, fail loudly at
        # startup rather than papering over a misconfigured deploy.
        self._collection = client.get_collection(self._collection_name)

    async def search(
        self,
        query_embedding: list[float],
        top_k: int,
        where: dict[str, Any] | None = None,
    ) -> list[RetrievedChunk]:
        return await asyncio.to_thread(
            self._search_sync, query_embedding, top_k, where
        )

    def _search_sync(
        self,
        query_embedding: list[float],
        top_k: int,
        where: dict[str, Any] | None,
    ) -> list[RetrievedChunk]:
        result = self._collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            where=where,
            include=["documents", "metadatas", "distances"],
        )

        # Chroma returns each field as a list-of-lists keyed by query. We
        # always issue a single query so we always take index 0.
        ids = result.get("ids", [[]])[0]
        docs = result.get("documents", [[]])[0]
        metas = result.get("metadatas", [[]])[0]
        dists = result.get("distances", [[]])[0]

        if not ids:
            return []

        # ChromaDB's cosine "distance" is 1 - cosine_similarity. Normalize
        # back to similarity in [0, 1] so callers don't have to remember
        # which direction is "better."
        return [
            RetrievedChunk(
                chunk_id=cid,
                text=doc,
                score=max(0.0, 1.0 - dist),
                source="vector",
                metadata=dict(meta) if meta else {},
            )
            for cid, doc, meta, dist in zip(ids, docs, metas, dists)
        ]

    async def count(self) -> int:
        return await asyncio.to_thread(self._collection.count)


class BM25SearchStore:
    """Async wrapper around a bm25s index."""

    def __init__(self, settings: Settings) -> None:
        self._retriever = bm25s.BM25.load(str(settings.bm25_index_dir))
        self._chunk_ids = self._load_chunk_ids(settings.bm25_chunk_ids_path)
        self._chunks_by_id = self._load_chunks_by_id(settings.chunks_jsonl_path)

        # Sanity check at startup: the BM25 ids file and chunks.jsonl
        # should agree on chunk_ids, or we'll return ids that don't have
        # corresponding text/metadata.
        missing = set(self._chunk_ids) - set(self._chunks_by_id.keys())
        if missing:
            logger.warning(
                "BM25SearchStore: %d chunk_ids in bm25 ids file have no chunk in chunks.jsonl "
                "(sample: %s). Index may be stale.",
                len(missing), list(missing)[:3],
            )

    @staticmethod
    def _load_chunk_ids(path: Path) -> list[str]:
        ids: list[str] = []
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                ids.append(json.loads(line)["chunk_id"])
        return ids

    @staticmethod
    def _load_chunks_by_id(path: Path) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                cid = obj.get("chunk_id")
                if cid is not None:
                    out[cid] = obj
        return out

    async def search(self, query: str, top_k: int) -> list[RetrievedChunk]:
        return await asyncio.to_thread(self._search_sync, query, top_k)

    def _search_sync(self, query: str, top_k: int) -> list[RetrievedChunk]:
        tokens = _tokenize(query)
        if not tokens:
            return []

        # bm25s raises if k > corpus size; ChromaDB silently returns fewer
        # results in that case. Match Chroma's behaviour so callers can ask
        # for an aspirational top_k without crashing on small corpora.
        effective_k = min(top_k, len(self._chunk_ids))
        if effective_k == 0:
            return []

        # bm25s' retrieve returns (results, scores) arrays of shape (1, k)
        # for a single-query call. show_progress=False keeps stderr quiet in
        # the verify and admin tools.
        results, scores = self._retriever.retrieve(
            [tokens], k=effective_k, show_progress=False
        )

        chunks_out: list[RetrievedChunk] = []
        for idx, score in zip(results[0], scores[0]):
            cid = self._chunk_ids[int(idx)]
            chunk = self._chunks_by_id.get(cid)
            if chunk is None:
                # Stale index entry — log and skip rather than fail the
                # whole query.
                logger.debug("BM25 hit chunk_id %s has no corresponding chunk; skipping", cid)
                continue
            chunks_out.append(
                RetrievedChunk(
                    chunk_id=cid,
                    text=chunk["text"],
                    score=float(score),
                    source="bm25",
                    metadata=dict(chunk.get("metadata", {})),
                )
            )
        return chunks_out