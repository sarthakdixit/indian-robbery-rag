"""Read the corpus version from the manifest.

The corpus version is a single source of truth for cache invalidation. Every
chunk in chunks.jsonl carries `corpus_version` written at chunk time. Every
ChromaDB document and BM25 record carries the same. The backend's cache
entries (built in later batches) also carry it. Bumping `corpus_version` in
sources.yaml and re-running the ingestion pipeline invalidates all caches
implicitly because the cached `corpus_version` no longer matches the live
one.

This module exists as a separate file (rather than inlined in the index
builders) so that `from corpus_version import read_corpus_version` is a
two-line read with no other dependencies — no need to import the heavy
ChromaDB or Pydantic schemas just to read a string from YAML.
"""

from __future__ import annotations

from pathlib import Path

import yaml


def read_corpus_version(manifest_path: Path) -> str:
    """Return the corpus_version string from sources.yaml.

    Raises FileNotFoundError if the manifest is missing and ValueError if
    the file exists but does not contain a top-level `corpus_version` field
    with a non-empty string value. Index builders must fail loudly here:
    indexing without a known corpus version would silently break cache
    invalidation downstream.
    """
    if not manifest_path.is_file():
        raise FileNotFoundError(f"manifest not found at {manifest_path}")

    raw = yaml.safe_load(manifest_path.read_text())
    if not isinstance(raw, dict):
        raise ValueError(f"manifest at {manifest_path} is not a YAML mapping")

    version = raw.get("corpus_version")
    if not version or not isinstance(version, str):
        raise ValueError(
            f"manifest at {manifest_path} is missing a non-empty `corpus_version`"
        )

    return version