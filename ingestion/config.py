"""Centralized file paths used across the ingestion pipeline.

This module exists so individual scripts don't each redefine
  REPO_ROOT / "ingestion" / "data" / "chunks.jsonl"
and drift over time. Add a new path here when adding a new step.

Scope is intentionally narrow: paths only. Domain thresholds, model names,
and tuning constants stay in `constants.py` within each owning package
(per AGENT.md §15). The rationale is that paths are genuinely cross-cutting
(every step reads/writes paths from other steps), while a threshold is
internal to its owning module.
"""

from __future__ import annotations

from pathlib import Path


REPO_ROOT: Path = Path(__file__).resolve().parents[1]

# Top-level manifest. Edited by classifier; read by normalize, chunk, index.
SOURCES_YAML: Path = REPO_ROOT / "sources.yaml"

# Raw corpus root. Read-only at runtime; written by manual download.
DATA_ROOT: Path = REPO_ROOT / "data"

# Intermediate and final outputs from the ingestion pipeline. Everything
# under this directory is regenerable; safe to delete and rebuild.
INGESTION_DATA: Path = REPO_ROOT / "ingestion" / "data"

# Step outputs, in pipeline order.
NORMALIZED_JSONL: Path = INGESTION_DATA / "normalized.jsonl"
CHUNKS_JSONL: Path = INGESTION_DATA / "chunks.jsonl"
EMBEDDINGS_JSONL: Path = INGESTION_DATA / "embeddings.jsonl"
EMBEDDING_CACHE_DB: Path = INGESTION_DATA / "embedding_cache.sqlite"

# Final index artifacts consumed by the backend at query time.
CHROMA_DB_DIR: Path = INGESTION_DATA / "chroma_db"
BM25_INDEX_DIR: Path = INGESTION_DATA / "bm25_index"
BM25_CHUNK_IDS: Path = INGESTION_DATA / "bm25_chunk_ids.jsonl"


def all_paths() -> dict[str, Path]:
    """Return every named path; useful for diagnostic dumps."""
    return {
        "REPO_ROOT": REPO_ROOT,
        "SOURCES_YAML": SOURCES_YAML,
        "DATA_ROOT": DATA_ROOT,
        "INGESTION_DATA": INGESTION_DATA,
        "NORMALIZED_JSONL": NORMALIZED_JSONL,
        "CHUNKS_JSONL": CHUNKS_JSONL,
        "EMBEDDINGS_JSONL": EMBEDDINGS_JSONL,
        "EMBEDDING_CACHE_DB": EMBEDDING_CACHE_DB,
        "CHROMA_DB_DIR": CHROMA_DB_DIR,
        "BM25_INDEX_DIR": BM25_INDEX_DIR,
        "BM25_CHUNK_IDS": BM25_CHUNK_IDS,
    }