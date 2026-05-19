"""Build a BM25 keyword-search index over the chunks.

Output: ingestion/data/bm25_index/ (a directory written by bm25s.BM25.save).
The backend at query time loads it with bm25s.BM25.load and scores queries
against the indexed corpus, producing the keyword side of the hybrid retrieval
that complements ChromaDB's vector search.

Tokenization is intentionally simple:
  - lowercase
  - "§" -> "section " so users typing "section 397" match indexed "§397"
  - split on non-alphanumeric runs (preserves digits in citations like
    "2007 SCC 641" and section numbers like "397")
  - drop tokens shorter than 2 chars (filters punctuation residue without
    losing single-letter legal abbreviations like "v" which we want)
  - no stemming (legal terminology relies on precise word forms;
    "robbery"/"robber"/"robbed" each have distinct legal meaning)
  - no stopwords (legal queries often hinge on small words: "any", "shall",
    "may"; aggressive stopword removal hurts more than it helps)

We also build a parallel id list (`chunk_ids.jsonl`) so that ranking by
position in the BM25 retrieve() output maps back to the same chunk_ids
that ChromaDB returns. Hybrid retrieval at query time fuses results from
both indices by chunk_id.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from pathlib import Path

try:
    import bm25s  # type: ignore[import-untyped]
except ImportError:
    print("bm25s is required. Install with: pip install bm25s", file=sys.stderr)
    sys.exit(2)


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CHUNKS = REPO_ROOT / "ingestion" / "data" / "chunks.jsonl"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "ingestion" / "data" / "bm25_index"
DEFAULT_IDS_PATH = REPO_ROOT / "ingestion" / "data" / "bm25_chunk_ids.jsonl"

# Tokenizer regex: any run of non-alphanumeric characters is a separator.
# Underscore is NOT a separator so multi-token legal terms stay intact if any
# slip through with underscores (rare; defensive).
_TOKEN_SPLIT_RE = re.compile(r"[^a-z0-9_]+")

MIN_TOKEN_LEN: int = 2

logger = logging.getLogger("build_bm25")


def configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )


def tokenize(text: str) -> list[str]:
    """Tokenize a single text into search tokens.

    Used both at index time (over chunk text) and at query time (over user
    questions). Must be deterministic; same input always produces same
    tokens.
    """
    lowered = text.lower().replace("§", "section ")
    raw_tokens = _TOKEN_SPLIT_RE.split(lowered)
    return [tok for tok in raw_tokens if len(tok) >= MIN_TOKEN_LEN]


def load_chunks(path: Path) -> tuple[list[str], list[str]]:
    """Return (chunk_ids, texts) preserving order."""
    chunk_ids: list[str] = []
    texts: list[str] = []
    with path.open(encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            cid = obj.get("chunk_id")
            text = obj.get("text")
            if not cid or not text:
                logger.warning("line %d: missing chunk_id or text; skipping", line_no)
                continue
            chunk_ids.append(cid)
            texts.append(text)
    return chunk_ids, texts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_CHUNKS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--ids-path", type=Path, default=DEFAULT_IDS_PATH)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    configure_logging(args.verbose)

    input_path: Path = args.input.resolve()
    output_dir: Path = args.output_dir.resolve()
    ids_path: Path = args.ids_path.resolve()

    if not input_path.is_file():
        logger.error("chunks input not found at %s", input_path)
        return 2

    logger.info("loading chunks from %s", input_path)
    chunk_ids, texts = load_chunks(input_path)
    logger.info("loaded %d chunks", len(chunk_ids))

    if not chunk_ids:
        logger.error("no chunks to index")
        return 1

    logger.info("tokenizing...")
    tokenized_corpus = [tokenize(text) for text in texts]
    avg_tokens = sum(len(t) for t in tokenized_corpus) / len(tokenized_corpus)
    logger.info("average tokens per chunk: %.1f", avg_tokens)

    logger.info("building BM25 index...")
    retriever = bm25s.BM25()
    retriever.index(tokenized_corpus)

    output_dir.parent.mkdir(parents=True, exist_ok=True)
    logger.info("saving index to %s", output_dir)
    retriever.save(str(output_dir))

    ids_path.parent.mkdir(parents=True, exist_ok=True)
    logger.info("saving chunk-id mapping to %s", ids_path)
    with ids_path.open("w", encoding="utf-8") as out:
        for cid in chunk_ids:
            out.write(json.dumps({"chunk_id": cid}) + "\n")

    logger.info("done: %d chunks indexed", len(chunk_ids))
    return 0


if __name__ == "__main__":
    sys.exit(main())