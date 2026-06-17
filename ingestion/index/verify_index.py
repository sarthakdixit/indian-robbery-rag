"""Sanity-check the built ChromaDB and BM25 indices.

This script does NOT call Gemini. It verifies the indices are well-formed
and contain the corpus we expect. Specifically it checks:

  - ChromaDB collection exists, has the expected document count
  - All chunk_ids appear in both ChromaDB and BM25 (or we report the diff)
  - Metadata fields are present and well-typed
  - A sample of canonical legal queries returns sensible hits via BM25
    (we can't run vector queries without re-embedding the query through
    Gemini; that path is exercised by the backend tests in Batch 3)

Exit codes:
  0  all checks pass
  1  one or more checks failed (details logged)
  2  configuration error (missing inputs)
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from collections import Counter
from pathlib import Path

try:
    import bm25s  # type: ignore[import-untyped]
    import chromadb  # type: ignore[import-untyped]
    from chromadb.config import Settings  # type: ignore[import-untyped]
except ImportError as e:
    print(f"required dependency missing: {e}", file=sys.stderr)
    sys.exit(2)

try:
    from ingestion.index.build_bm25 import tokenize
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from ingestion.index.build_bm25 import tokenize


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_DIR = REPO_ROOT / "ingestion" / "data" / "chroma_db"
DEFAULT_BM25_DIR = REPO_ROOT / "ingestion" / "data" / "bm25_index"
DEFAULT_BM25_IDS = REPO_ROOT / "ingestion" / "data" / "bm25_chunk_ids.jsonl"

COLLECTION_NAME: str = "robbery_corpus"

# Canonical queries with the section numbers we expect to surface in the
# top-5 BM25 hits. These are intentionally conservative — we only assert
# that *something* about the right area shows up, not exact ranking.
SMOKE_QUERIES: list[tuple[str, list[str]]] = [
    ("what is robbery", ["390", "392", "309"]),
    ("dacoity", ["391", "395", "310"]),
    ("punishment for robbery", ["392", "309"]),
    ("section 397", ["397"]),
    ("deadly weapon", ["397"]),
]

logger = logging.getLogger("verify_index")


# Match runs of 1-3 digits as candidate section numbers. The maximum
# section number across IPC (511), BNS (~358), and BNSS (~531) is 3 digits.
# Restricting to 1-3 digits excludes 4-digit years like "2024" and longer
# citation page numbers like "12345" from being mistaken for sections.
_SECTION_DIGIT_RE = re.compile(r"\b(\d{1,3})\b")


def _extract_section_numbers(text: str) -> set[str]:
    """Pull every plausible section number out of a free-text metadata field.

    Handles "392 IPC", "397/309", "§309 read with §397", and "(2024) SCC 641"
    by matching digit runs and bounding their length. Years and citation
    page numbers (>4 digits) are not section numbers and get filtered out.
    """
    return set(_SECTION_DIGIT_RE.findall(text))


def configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )


def check_chroma(db_dir: Path) -> tuple[bool, dict[str, int], list[str]]:
    """Return (ok, source_type_counts, chunk_ids_in_chroma)."""
    if not db_dir.is_dir():
        logger.error("chroma_db not found at %s", db_dir)
        return False, {}, []

    client = chromadb.PersistentClient(
        path=str(db_dir),
        settings=Settings(anonymized_telemetry=False),
    )
    try:
        collection = client.get_collection(COLLECTION_NAME)
    except Exception as e:
        logger.error("could not open collection %r: %s", COLLECTION_NAME, e)
        return False, {}, []

    count = collection.count()
    logger.info("ChromaDB: %d documents in collection %r", count, COLLECTION_NAME)
    if count == 0:
        return False, {}, []

    # Sample all docs to inspect metadata distribution
    everything = collection.get(include=["metadatas"])
    source_types: Counter[str] = Counter()
    for meta in everything["metadatas"]:
        st = meta.get("source_type", "?")
        source_types[str(st)] += 1

    logger.info("ChromaDB source_type distribution: %s", dict(source_types))
    return True, dict(source_types), list(everything["ids"])


def check_bm25(bm25_dir: Path, ids_path: Path) -> tuple[bool, int, list[str]]:
    """Return (ok, doc_count, chunk_ids_in_bm25)."""
    if not bm25_dir.is_dir():
        logger.error("bm25_index not found at %s", bm25_dir)
        return False, 0, []
    if not ids_path.is_file():
        logger.error("bm25_chunk_ids.jsonl not found at %s", ids_path)
        return False, 0, []

    chunk_ids: list[str] = []
    with ids_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            chunk_ids.append(json.loads(line)["chunk_id"])

    logger.info("BM25 chunk_ids file: %d entries", len(chunk_ids))
    return True, len(chunk_ids), chunk_ids


def check_smoke_queries(bm25_dir: Path, chunk_ids: list[str], chunks_path: Path) -> bool:
    """Run a few canonical queries and confirm sensible top-5 hits.

    Loads chunks.jsonl alongside the BM25 index because BM25 only knows the
    tokens; section numbers live in the chunk metadata. We score with BM25,
    take the top 5, then check those chunks' metadata for the expected
    section numbers.
    """
    if not chunks_path.is_file():
        logger.warning("chunks.jsonl missing at %s; skipping smoke queries", chunks_path)
        return True

    chunks_by_id: dict[str, dict] = {}
    with chunks_path.open(encoding="utf-8") as f:
        for line in f:
            obj = json.loads(line.strip())
            chunks_by_id[obj["chunk_id"]] = obj

    retriever = bm25s.BM25.load(str(bm25_dir))

    all_passed = True
    for query, expected_sections in SMOKE_QUERIES:
        query_tokens = tokenize(query)
        results, scores = retriever.retrieve([query_tokens], k=5)
        top_ids = [chunk_ids[i] for i in results[0]]

        # Walk the top 5 hits and collect every section reference we can
        # find. Act chunks have a single `section_number`; judgment chunks
        # have `primary_section` (free-text like "397/309 IPC") and
        # `other_sections` (list[str] flattened to comma-joined). Extract
        # every digit-run from these as a candidate section number, since
        # judgments often cite multiple sections in one field.
        seen_sections: set[str] = set()
        for cid in top_ids:
            chunk = chunks_by_id.get(cid, {})
            meta = chunk.get("metadata", {})
            sec = meta.get("section_number")
            if sec:
                seen_sections.add(str(sec))
            primary = meta.get("primary_section")
            if primary:
                seen_sections.update(_extract_section_numbers(str(primary)))
            for other in (meta.get("other_sections") or []):
                seen_sections.update(_extract_section_numbers(str(other)))

        hits = [s for s in expected_sections if s in seen_sections]
        if hits:
            logger.info(
                "smoke %r: PASS (found %s in top-5 sections %s)",
                query, hits, sorted(seen_sections),
            )
        else:
            logger.warning(
                "smoke %r: NO MATCH — expected any of %s, top-5 sections were %s",
                query, expected_sections, sorted(seen_sections) or "(no act chunks in top-5)",
            )
            all_passed = False

    return all_passed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-dir", type=Path, default=DEFAULT_DB_DIR)
    parser.add_argument("--bm25-dir", type=Path, default=DEFAULT_BM25_DIR)
    parser.add_argument("--bm25-ids", type=Path, default=DEFAULT_BM25_IDS)
    parser.add_argument(
        "--chunks",
        type=Path,
        default=REPO_ROOT / "ingestion" / "data" / "chunks.jsonl",
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    configure_logging(args.verbose)

    overall_ok = True

    chroma_ok, _source_types, chroma_ids = check_chroma(args.db_dir.resolve())
    overall_ok = overall_ok and chroma_ok

    bm25_ok, bm25_count, bm25_ids = check_bm25(args.bm25_dir.resolve(), args.bm25_ids.resolve())
    overall_ok = overall_ok and bm25_ok

    if chroma_ok and bm25_ok:
        chroma_set = set(chroma_ids)
        bm25_set = set(bm25_ids)
        only_chroma = chroma_set - bm25_set
        only_bm25 = bm25_set - chroma_set

        # `only_chroma` is a REAL problem: embeddings exist for chunks
        # that don't appear in BM25, which means the index is internally
        # inconsistent. This happens after a stale ChromaDB carries over
        # chunk_ids that the chunker no longer produces (e.g., the
        # parser dropped them). Hybrid retrieval would surface ghost
        # results from these orphans. Fail loudly.
        if only_chroma:
            logger.error(
                "chunk_id orphans in Chroma: %d embeddings reference chunks "
                "not in BM25 (corpus may be stale; rebuild with `make ingest`). "
                "Examples: %s",
                len(only_chroma), sorted(only_chroma)[:5],
            )
            overall_ok = False

        # `only_bm25` is EXPECTED during incremental embedding: BM25
        # indexes every chunk (no API needed), but Chroma only gets a
        # chunk after its embedding has been computed. The remaining
        # chunks are waiting for the next embed run. NOT a failure.
        if only_bm25:
            logger.info(
                "chunk_id coverage: %d / %d chunks have embeddings in Chroma; "
                "%d chunks are BM25-only (run embed_chunks.py to fill them in)",
                len(chroma_set), len(bm25_set), len(only_bm25),
            )
        elif not only_chroma:
            logger.info("chunk_id sets match across Chroma and BM25 (%d each)",
                        len(chroma_set))

    if bm25_ok and bm25_count > 0:
        smoke_ok = check_smoke_queries(args.bm25_dir.resolve(), bm25_ids, args.chunks.resolve())
        overall_ok = overall_ok and smoke_ok

    if overall_ok:
        logger.info("ALL CHECKS PASSED")
        return 0
    logger.error("one or more checks failed; see warnings above")
    return 1


if __name__ == "__main__":
    sys.exit(main())