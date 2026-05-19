"""Chunk normalized documents into embedding-ready records.

Reads ingestion/data/normalized.jsonl (output of Chunk 1.3), dispatches
to chunk_act or chunk_judgment based on source_type, and writes
ingestion/data/chunks.jsonl with full Chunk records.

The chunker is fully deterministic — re-running on the same input
produces identical output (same chunk_ids, same byte order). This
matters for cache key stability in the backend.

Usage:
  python ingestion/chunk/run_chunking.py
  python ingestion/chunk/run_chunking.py --input X.jsonl --output Y.jsonl
  python ingestion/chunk/run_chunking.py --corpus-version 2026.05.14

Exit codes:
  0  chunking completed
  1  one or more input records failed
  2  configuration error (input missing, etc.)
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

try:
    from ingestion.chunk.chunker import chunk_act, chunk_judgment
    from ingestion.normalize.schema import NormalizedAct, NormalizedJudgment, SourceType
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from ingestion.chunk.chunker import chunk_act, chunk_judgment
    from ingestion.normalize.schema import NormalizedAct, NormalizedJudgment, SourceType


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT = REPO_ROOT / "ingestion" / "data" / "normalized.jsonl"
DEFAULT_OUTPUT = REPO_ROOT / "ingestion" / "data" / "chunks.jsonl"
DEFAULT_MANIFEST = REPO_ROOT / "sources.yaml"

logger = logging.getLogger("chunk")


def configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )


def read_corpus_version(manifest_path: Path) -> str | None:
    if not manifest_path.is_file():
        return None
    try:
        raw = yaml.safe_load(manifest_path.read_text())
        version = raw.get("corpus_version") if isinstance(raw, dict) else None
        return str(version) if version else None
    except (OSError, yaml.YAMLError):
        return None


def parse_normalized_record(raw_obj: dict[str, Any]) -> NormalizedAct | NormalizedJudgment | None:
    source_type = raw_obj.get("source_type")
    try:
        if source_type == SourceType.ACT.value:
            return NormalizedAct.model_validate(raw_obj)
        if source_type == SourceType.JUDGMENT.value:
            return NormalizedJudgment.model_validate(raw_obj)
    except ValidationError as e:
        logger.error("record validation failed: %s", e.errors())
        return None
    logger.error("unknown source_type %r", source_type)
    return None


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument(
        "--corpus-version",
        type=str,
        default=None,
        help="Override corpus version. Default: read from sources.yaml.",
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    configure_logging(args.verbose)

    input_path: Path = args.input.resolve()
    output_path: Path = args.output.resolve()
    manifest_path: Path = args.manifest.resolve()

    if not input_path.is_file():
        logger.error("input not found at %s", input_path)
        logger.error("run ingestion/normalize/parse_judgments.py first")
        return 2

    corpus_version = args.corpus_version or read_corpus_version(manifest_path)
    if not corpus_version:
        logger.error("corpus_version not set in %s and --corpus-version not provided", manifest_path)
        return 2

    logger.info("chunking with corpus_version=%s", corpus_version)
    logger.info("input:  %s", input_path)
    logger.info("output: %s", output_path)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    records_in = 0
    records_failed = 0
    chunks_written = 0
    chunks_by_type: dict[str, int] = {"act": 0, "judgment": 0}

    with input_path.open(encoding="utf-8") as src, output_path.open("w", encoding="utf-8") as dst:
        for line_number, line in enumerate(src, start=1):
            line = line.strip()
            if not line:
                continue

            try:
                raw_obj = json.loads(line)
            except json.JSONDecodeError as e:
                logger.error("line %d: invalid JSON: %s", line_number, e)
                records_failed += 1
                continue

            records_in += 1
            doc = parse_normalized_record(raw_obj)
            if doc is None:
                records_failed += 1
                continue

            if isinstance(doc, NormalizedAct):
                identifier = f"act {doc.short_name}"
                chunk_iter = chunk_act(doc, corpus_version)
            else:
                identifier = f"judgment {doc.folder} ({doc.case_id})"
                chunk_iter = chunk_judgment(doc, corpus_version)

            produced = 0
            for chunk in chunk_iter:
                dst.write(chunk.model_dump_json() + "\n")
                chunks_written += 1
                chunks_by_type[chunk.metadata.source_type.value] += 1
                produced += 1

            if produced == 0:
                logger.warning("%s: produced 0 chunks", identifier)
            else:
                logger.info("%s: %d chunk(s)", identifier, produced)

    logger.info(
        "done: %d records in (%d failed), %d chunks out (%d acts, %d judgments)",
        records_in, records_failed, chunks_written,
        chunks_by_type["act"], chunks_by_type["judgment"],
    )

    if records_failed > 0 or chunks_written == 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())