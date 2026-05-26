"""Embed chunks for ChromaDB indexing.

Reads ingestion/data/chunks.jsonl (output of Batch 1.4) and produces
ingestion/data/embeddings.jsonl with one record per chunk:

    {"chunk_id": "...", "embedding": [...], "model": "...", "task_type": "..."}

Flow:
  1. Load chunks.
  2. For each chunk, check the SQLite cache. If hit, reuse the vector.
  3. Group cache-misses into batches of MAX_BATCH_SIZE and call Gemini.
  4. Write each successful batch back to the cache *before* moving on,
     so a quota stop or crash never loses progress.
  5. On QuotaExhausted, write what we have to embeddings.jsonl and exit
     with code 3. Re-running the script picks up where we left off
     because everything embedded so far is in the cache.

Usage:
  GEMINI_API_KEY=... python ingestion/embed/embed_chunks.py
  GEMINI_API_KEY=... python ingestion/embed/embed_chunks.py --dry-run
  GEMINI_API_KEY=... python ingestion/embed/embed_chunks.py --limit 50

Exit codes:
  0  all chunks embedded
  1  one or more permanent embedding failures (not quota)
  2  configuration error (missing API key, missing input, etc.)
  3  daily quota exhausted; re-run after midnight Pacific to resume
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

try:
    from ingestion.embed.cache import EmbeddingCache
    from ingestion.embed.gemini_client import (
        EmbeddingsError,
        EmbeddingsOk,
        GeminiEmbeddingsClient,
        MAX_BATCH_SIZE,
        QuotaExhausted,
    )
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from ingestion.embed.cache import EmbeddingCache
    from ingestion.embed.gemini_client import (
        EmbeddingsError,
        EmbeddingsOk,
        GeminiEmbeddingsClient,
        MAX_BATCH_SIZE,
        QuotaExhausted,
    )


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CHUNKS = REPO_ROOT / "ingestion" / "data" / "chunks.jsonl"
DEFAULT_OUTPUT = REPO_ROOT / "ingestion" / "data" / "embeddings.jsonl"
DEFAULT_CACHE = REPO_ROOT / "ingestion" / "data" / "embedding_cache.sqlite"

SECONDS_BETWEEN_BATCHES: float = 1.0
QUOTA_EXIT_CODE: int = 3

# Gemini quota 429 handling.
#
# Empirically (May 2026, free-tier gemini-embedding-001), the API returns
# retry_after ≈ 30-60s for BOTH per-minute throttles AND daily-quota
# exhaustion. We cannot distinguish them from retry_after alone.
#
# Discriminator: consecutive 429s on the SAME batch.
#   - Per-minute throttle: 1-2 retries succeed (window slides open)
#   - Daily quota:        every retry fails (window doesn't reopen until tomorrow)
#
# Decision tree per 429:
#   1. retry_after missing or > AUTO_RETRY_MAX_WAIT_SECONDS → bail (long signal)
#   2. consecutive 429s on this same batch >= CONSECUTIVE_429_BAIL_THRESHOLD → bail (daily-shaped)
#   3. total auto-retries this run >= AUTO_RETRY_MAX_COUNT → bail (safety cap)
#   4. otherwise → sleep retry_after + pad seconds, retry the same batch
AUTO_RETRY_MAX_WAIT_SECONDS: float = 120.0

# Three consecutive 429s on the same batch with no intervening success means
# the window isn't reopening — almost certainly daily quota, regardless of
# what retry_after claims. Three lets RPM win-or-lose decisively (a
# legitimate RPM throttle wins within 1-2 retries; daily quota loses 3 in a
# row). Below 3, occasional retry-then-still-fail patterns under RPM could
# trigger false positives.
CONSECUTIVE_429_BAIL_THRESHOLD: int = 3

# Hard cap on total quota retries within a single run, regardless of how
# short the retry_after windows are. Prevents pathological loops if the API
# misbehaves. With the consecutive-429 check firing earlier, this is mostly
# a paranoia backstop.
AUTO_RETRY_MAX_COUNT: int = 30

# Small safety pad added to the API-reported retry_after to account for clock
# drift and sliding-window quotas where the exact second the window opens
# isn't deterministic.
AUTO_RETRY_PAD_SECONDS: float = 5.0

logger = logging.getLogger("embed")


def configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )


def load_chunks(path: Path) -> list[dict[str, object]]:
    chunks: list[dict[str, object]] = []
    with path.open(encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                chunks.append(json.loads(line))
            except json.JSONDecodeError as e:
                logger.error("chunks.jsonl line %d: invalid JSON: %s", line_no, e)
                raise
    return chunks


def write_embeddings_output(
    output_path: Path,
    chunks: list[dict[str, object]],
    cache: EmbeddingCache,
    model: str,
    task_type: str,
) -> int:
    """Write embeddings.jsonl with one record per chunk that has a cached vector.

    Chunks without a cached vector are skipped (they'll be filled in on the
    next run). Returns the number of records written.
    """
    written = 0
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as out:
        for chunk in chunks:
            text = chunk["text"]
            assert isinstance(text, str)
            vector = cache.get(text, model, task_type)
            if vector is None:
                continue
            record = {
                "chunk_id": chunk["chunk_id"],
                "embedding": vector,
                "model": model,
                "task_type": task_type,
            }
            out.write(json.dumps(record) + "\n")
            written += 1
    return written


def embed_misses(
    client: GeminiEmbeddingsClient,
    cache: EmbeddingCache,
    misses: list[tuple[int, str]],
    auto_retry_max_wait: float = AUTO_RETRY_MAX_WAIT_SECONDS,
    auto_retry_max_count: int = AUTO_RETRY_MAX_COUNT,
    consecutive_429_bail: int = CONSECUTIVE_429_BAIL_THRESHOLD,
) -> tuple[int, int, QuotaExhausted | None]:
    """Embed all cache-miss texts in batches; cache them as we go.

    Quota 429 handling has three exit conditions, checked in order:
      1. retry_after missing or > auto_retry_max_wait     -> bail
      2. >= consecutive_429_bail 429s on the same batch    -> bail (daily-shaped)
      3. >= auto_retry_max_count total retries this run    -> bail (safety cap)
    Otherwise sleep retry_after + pad and retry the same batch.

    The consecutive-429-per-batch check is the discriminator between
    per-minute throttles and daily-quota exhaustion. Per-minute throttles
    reopen within 60-90s; daily quotas don't reopen until midnight Pacific.
    Both shapes return similar retry_after values, so retry_after alone
    can't tell them apart.

    Returns (successfully_embedded, permanently_failed, quota_exhausted_or_none).
    """
    succeeded = 0
    failed = 0
    quota_signal: QuotaExhausted | None = None
    auto_retries_used = 0
    consecutive_429s_on_current_batch = 0

    total_batches = (len(misses) + MAX_BATCH_SIZE - 1) // MAX_BATCH_SIZE

    batch_index = 0
    while batch_index < total_batches:
        start = batch_index * MAX_BATCH_SIZE
        end = min(start + MAX_BATCH_SIZE, len(misses))
        batch = misses[start:end]
        texts = [text for _, text in batch]

        logger.info(
            "[batch %d/%d] embedding %d texts (cumulative success=%d)",
            batch_index + 1, total_batches, len(texts), succeeded,
        )

        result = client.embed_batch(texts)

        if isinstance(result, QuotaExhausted):
            retry_after = result.retry_after_seconds
            consecutive_429s_on_current_batch += 1

            # Bail condition 1: retry_after missing or unhelpfully long.
            if retry_after is None or retry_after > auto_retry_max_wait:
                why = (
                    "retry_after unknown" if retry_after is None
                    else f"retry_after {retry_after:.0f}s > threshold {auto_retry_max_wait:.0f}s"
                )
                logger.warning(
                    "  QUOTA EXHAUSTED at batch %d/%d (%s). Stopping.",
                    batch_index + 1, total_batches, why,
                )
                logger.warning(
                    "  Successfully embedded so far: %d. Re-run after quota resets to continue.",
                    succeeded,
                )
                quota_signal = result
                break

            # Bail condition 2: same batch keeps failing — almost certainly
            # daily quota wearing a short-retry_after mask.
            if consecutive_429s_on_current_batch >= consecutive_429_bail:
                logger.warning(
                    "  QUOTA EXHAUSTED at batch %d/%d (%d consecutive 429s on this batch — "
                    "daily quota likely; retry_after=%ss does not reflect actual reopen time). Stopping.",
                    batch_index + 1, total_batches,
                    consecutive_429s_on_current_batch, retry_after,
                )
                logger.warning(
                    "  Successfully embedded so far: %d. Re-run tomorrow to continue.",
                    succeeded,
                )
                quota_signal = result
                break

            # Bail condition 3: total retry budget exhausted (safety cap).
            if auto_retries_used >= auto_retry_max_count:
                logger.warning(
                    "  QUOTA EXHAUSTED at batch %d/%d (auto-retry budget exhausted "
                    "(%d/%d)). Stopping.",
                    batch_index + 1, total_batches,
                    auto_retries_used, auto_retry_max_count,
                )
                logger.warning(
                    "  Successfully embedded so far: %d. Re-run after quota resets to continue.",
                    succeeded,
                )
                quota_signal = result
                break

            # Otherwise: sleep and retry the same batch.
            sleep_for = retry_after + AUTO_RETRY_PAD_SECONDS
            auto_retries_used += 1
            logger.info(
                "  Quota 429 at batch %d/%d (consecutive %d on this batch). "
                "Sleeping %.1fs and retrying (auto-retry %d/%d).",
                batch_index + 1, total_batches,
                consecutive_429s_on_current_batch, sleep_for,
                auto_retries_used, auto_retry_max_count,
            )
            time.sleep(sleep_for)
            # Do NOT advance batch_index — retry the same batch.
            continue

        if isinstance(result, EmbeddingsError):
            logger.error(
                "  PERMANENT FAILURE on batch %d/%d: %s",
                batch_index + 1, total_batches, result.raw_error[:200],
            )
            failed += len(batch)
            batch_index += 1
            consecutive_429s_on_current_batch = 0
            # Continue to next batch — one bad batch shouldn't kill the run
            continue

        assert isinstance(result, EmbeddingsOk)
        cache.put_many(
            list(zip(texts, result.vectors)),
            model=client.model,
            task_type=client.task_type,
        )
        succeeded += len(batch)
        batch_index += 1
        consecutive_429s_on_current_batch = 0

        if batch_index < total_batches:
            time.sleep(SECONDS_BETWEEN_BATCHES)

    return succeeded, failed, quota_signal


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_CHUNKS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--cache-db", type=Path, default=DEFAULT_CACHE)
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Embed at most N cache-miss chunks. Useful for staying under a daily quota.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report cache hits/misses without calling Gemini or writing output.",
    )
    parser.add_argument(
        "--auto-retry-max-wait",
        type=float,
        default=AUTO_RETRY_MAX_WAIT_SECONDS,
        help=(
            "If Gemini returns a quota 429 with a retry_after <= this many seconds, "
            "sleep and retry the same batch instead of exiting. Default: %(default)ss. "
            "Set to 0 to disable auto-retry (bail on any quota error)."
        ),
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    configure_logging(args.verbose)

    input_path: Path = args.input.resolve()
    output_path: Path = args.output.resolve()
    cache_path: Path = args.cache_db.resolve()

    if not input_path.is_file():
        logger.error("chunks input not found at %s", input_path)
        logger.error("run ingestion/chunk/run_chunking.py first")
        return 2

    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not args.dry_run and not api_key:
        logger.error("GEMINI_API_KEY environment variable is required (or use --dry-run).")
        return 2

    logger.info("loading chunks from %s", input_path)
    chunks = load_chunks(input_path)
    logger.info("loaded %d chunks", len(chunks))

    with EmbeddingCache(cache_path) as cache:
        client = GeminiEmbeddingsClient(api_key=api_key) if not args.dry_run else None
        model = client.model if client else "text-embedding-004"
        task_type = client.task_type if client else "RETRIEVAL_DOCUMENT"

        hits = 0
        misses: list[tuple[int, str]] = []
        for i, chunk in enumerate(chunks):
            text = chunk["text"]
            assert isinstance(text, str)
            if cache.get(text, model, task_type) is not None:
                hits += 1
            else:
                misses.append((i, text))

        logger.info(
            "cache: %d hits, %d misses (cache total entries: %d)",
            hits, len(misses), cache.count(model, task_type),
        )

        if args.limit is not None and len(misses) > args.limit:
            logger.info("limiting to first %d misses (of %d)", args.limit, len(misses))
            misses = misses[: args.limit]

        if args.dry_run:
            logger.info("dry-run: would embed %d texts in %d batch(es) of up to %d each",
                        len(misses),
                        (len(misses) + MAX_BATCH_SIZE - 1) // MAX_BATCH_SIZE,
                        MAX_BATCH_SIZE)
            return 0

        if not misses:
            logger.info("all chunks already in cache; writing embeddings.jsonl")
            written = write_embeddings_output(output_path, chunks, cache, model, task_type)
            logger.info("wrote %d embedding records to %s", written, output_path)
            return 0

        assert client is not None
        succeeded, failed, quota_signal = embed_misses(
            client, cache, misses,
            auto_retry_max_wait=args.auto_retry_max_wait,
        )

        # Always write whatever we have, even on partial runs
        written = write_embeddings_output(output_path, chunks, cache, model, task_type)
        logger.info(
            "wrote %d embedding records to %s (this run: %d new, %d failed)",
            written, output_path, succeeded, failed,
        )

        if quota_signal is not None:
            return QUOTA_EXIT_CODE
        return 1 if failed > 0 else 0


if __name__ == "__main__":
    sys.exit(main())