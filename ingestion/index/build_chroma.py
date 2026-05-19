"""Build the ChromaDB index from chunks.jsonl + embeddings.jsonl.

Output: ingestion/data/chroma_db/ (the ChromaDB persistent client's storage
directory). The backend at runtime opens this with chromadb.PersistentClient
and queries the collection by name.

Why this script does NOT call Gemini:
  - All embeddings are pre-computed by ingestion/embed/embed_chunks.py and
    written to embeddings.jsonl. This script joins chunks with their
    embeddings by chunk_id and hands them to Chroma. Decoupling embedding
    from indexing means we can re-build the Chroma index in seconds (no API
    calls, no quota) when only the index needs rebuilding.

Distance metric:
  - Set to "cosine" at collection creation time. Cannot be changed later.
    Gemini embeddings are normalized, so cosine is the natural choice.

Metadata flattening:
  - ChromaDB only accepts scalar metadata values (str/int/float/bool). The
    chunker's `JudgmentChunkMetadata.other_sections` is a list[str], so it
    is joined into a comma-separated string. None values are dropped.
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
from pathlib import Path
from typing import Any

try:
    import chromadb  # type: ignore[import-untyped]
    from chromadb.config import Settings  # type: ignore[import-untyped]
except ImportError:
    print("chromadb is required. Install with: pip install chromadb", file=sys.stderr)
    sys.exit(2)

try:
    from ingestion.index.corpus_version import read_corpus_version
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from ingestion.index.corpus_version import read_corpus_version


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CHUNKS = REPO_ROOT / "ingestion" / "data" / "chunks.jsonl"
DEFAULT_EMBEDDINGS = REPO_ROOT / "ingestion" / "data" / "embeddings.jsonl"
DEFAULT_DB_DIR = REPO_ROOT / "ingestion" / "data" / "chroma_db"
DEFAULT_MANIFEST = REPO_ROOT / "sources.yaml"

COLLECTION_NAME: str = "robbery_corpus"
DISTANCE_METRIC: str = "cosine"

logger = logging.getLogger("build_chroma")


def configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )


def load_chunks(path: Path) -> dict[str, dict[str, Any]]:
    """Return chunk_id -> chunk dict."""
    chunks: dict[str, dict[str, Any]] = {}
    with path.open(encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            cid = obj.get("chunk_id")
            if not cid:
                logger.warning("chunks line %d: missing chunk_id", line_no)
                continue
            chunks[cid] = obj
    return chunks


def load_embeddings(path: Path) -> dict[str, list[float]]:
    """Return chunk_id -> embedding vector."""
    embs: dict[str, list[float]] = {}
    with path.open(encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            cid = obj.get("chunk_id")
            vec = obj.get("embedding")
            if not cid or not vec:
                logger.warning("embeddings line %d: missing chunk_id or embedding", line_no)
                continue
            embs[cid] = vec
    return embs


def flatten_metadata(chunk: dict[str, Any], corpus_version: str) -> dict[str, str | int | float | bool]:
    """Convert nested chunk metadata into a flat dict of scalars.

    ChromaDB rejects list, dict, and None values in metadata. This function
    joins lists into comma-separated strings, drops None values, and adds
    top-level corpus_version + char_count + approx_token_count for filtering.
    """
    raw_meta = chunk.get("metadata", {})
    flat: dict[str, str | int | float | bool] = {}

    for key, value in raw_meta.items():
        if value is None:
            continue
        if isinstance(value, list):
            # other_sections: list[str] -> "392,394,397"
            flat[key] = ",".join(str(v) for v in value)
            continue
        if isinstance(value, (str, int, float, bool)):
            flat[key] = value
            continue
        # Fall back to str for anything unexpected (enum values, etc.)
        flat[key] = str(value)

    # Promote top-level chunk fields useful for filtering.
    flat["corpus_version"] = corpus_version
    if "char_count" in chunk:
        flat["char_count"] = int(chunk["char_count"])
    if "approx_token_count" in chunk:
        flat["approx_token_count"] = int(chunk["approx_token_count"])

    return flat


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chunks", type=Path, default=DEFAULT_CHUNKS)
    parser.add_argument("--embeddings", type=Path, default=DEFAULT_EMBEDDINGS)
    parser.add_argument("--db-dir", type=Path, default=DEFAULT_DB_DIR)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Delete the existing chroma_db/ directory before building. Default: error if it exists.",
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    configure_logging(args.verbose)

    chunks_path: Path = args.chunks.resolve()
    emb_path: Path = args.embeddings.resolve()
    db_dir: Path = args.db_dir.resolve()
    manifest_path: Path = args.manifest.resolve()

    for path, label in [(chunks_path, "chunks"), (emb_path, "embeddings")]:
        if not path.is_file():
            logger.error("%s input not found at %s", label, path)
            return 2

    try:
        corpus_version = read_corpus_version(manifest_path)
    except (FileNotFoundError, ValueError) as e:
        logger.error("could not read corpus_version: %s", e)
        return 2

    logger.info("building Chroma index for corpus_version=%s", corpus_version)

    if db_dir.exists():
        if args.reset:
            logger.warning("removing existing chroma_db at %s", db_dir)
            shutil.rmtree(db_dir)
        else:
            logger.error(
                "chroma_db already exists at %s. Use --reset to rebuild.", db_dir
            )
            return 2

    db_dir.mkdir(parents=True, exist_ok=True)

    logger.info("loading chunks from %s", chunks_path)
    chunks = load_chunks(chunks_path)
    logger.info("loaded %d chunks", len(chunks))

    logger.info("loading embeddings from %s", emb_path)
    embeddings = load_embeddings(emb_path)
    logger.info("loaded %d embeddings", len(embeddings))

    # Inner-join chunks and embeddings on chunk_id. Chunks without an
    # embedding are skipped with a warning (most likely they hit a quota
    # stop in the embed step; re-run embed to fill them in).
    joined_ids: list[str] = []
    joined_docs: list[str] = []
    joined_metas: list[dict[str, str | int | float | bool]] = []
    joined_embs: list[list[float]] = []

    missing_embeddings = 0
    for cid, chunk in chunks.items():
        vec = embeddings.get(cid)
        if vec is None:
            missing_embeddings += 1
            continue
        joined_ids.append(cid)
        joined_docs.append(chunk["text"])
        joined_metas.append(flatten_metadata(chunk, corpus_version))
        joined_embs.append(vec)

    if missing_embeddings > 0:
        logger.warning(
            "%d chunks have no embedding; not indexed. Run embed_chunks.py to fill them.",
            missing_embeddings,
        )

    if not joined_ids:
        logger.error("no chunks have embeddings; index would be empty")
        return 1

    logger.info(
        "%d chunks ready to index (with %d missing embeddings skipped)",
        len(joined_ids), missing_embeddings,
    )

    client = chromadb.PersistentClient(
        path=str(db_dir),
        settings=Settings(anonymized_telemetry=False),
    )
    collection = client.create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": DISTANCE_METRIC},
    )
    logger.info("created collection %r with distance=%s", COLLECTION_NAME, DISTANCE_METRIC)

    max_batch = getattr(client, "max_batch_size", None) or getattr(
        client, "get_max_batch_size", lambda: 5000
    )()
    logger.info("Chroma max_batch_size: %d", max_batch)

    total = len(joined_ids)
    for start in range(0, total, max_batch):
        end = min(start + max_batch, total)
        logger.info("adding %d-%d of %d ...", start, end, total)
        collection.add(
            ids=joined_ids[start:end],
            documents=joined_docs[start:end],
            metadatas=joined_metas[start:end],
            embeddings=joined_embs[start:end],
        )

    final_count = collection.count()
    logger.info("done: %d documents in collection %r", final_count, COLLECTION_NAME)
    return 0


if __name__ == "__main__":
    sys.exit(main())