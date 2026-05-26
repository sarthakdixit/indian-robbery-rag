"""Orchestrate the full ingestion pipeline.

Chains: verify_corpus -> classify (optional) -> normalize -> chunk ->
embed -> build_bm25 -> build_chroma -> verify_index.

The orchestrator does two useful things on top of running scripts in order:

1. **Staleness detection.** Each step checks whether its output is newer
   than its inputs. If so, the step is skipped with an "up-to-date" log.
   Use --force or --from STEP to override.

2. **Quota-stop propagation.** The embed step exits with code 3 when
   Gemini's daily quota is exhausted. The orchestrator detects this and
   exits 3 itself, so a Make wrapper or CI can branch on "stopped due
   to quota; resume tomorrow" vs other failures.

Steps are run as subprocesses (python -m ingestion.x.y) rather than
imported, because each step is a self-contained script with its own
exit code and logging. This keeps the orchestrator small and avoids
the import-side-effects mess of pulling every step's module into one
Python process.

Usage:
  python ingestion/run_ingestion.py
  python ingestion/run_ingestion.py --force                # rebuild everything
  python ingestion/run_ingestion.py --from chunk           # start at chunking
  python ingestion/run_ingestion.py --skip classify        # skip classifier
  python ingestion/run_ingestion.py --dry-run              # report plan, don't run

Exit codes:
  0  pipeline completed (some steps may have been skipped as up-to-date)
  1  one or more steps failed for non-quota reasons
  2  configuration error
  3  Gemini quota exhausted in embed step; re-run tomorrow to resume
"""

from __future__ import annotations

import argparse
import logging
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

try:
    from ingestion.config import (
        BM25_CHUNK_IDS,
        BM25_INDEX_DIR,
        CHROMA_DB_DIR,
        CHUNKS_JSONL,
        EMBEDDINGS_JSONL,
        INGESTION_DATA,
        NORMALIZED_JSONL,
        REPO_ROOT,
        SOURCES_YAML,
    )
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ingestion.config import (
        BM25_CHUNK_IDS,
        BM25_INDEX_DIR,
        CHROMA_DB_DIR,
        CHUNKS_JSONL,
        EMBEDDINGS_JSONL,
        INGESTION_DATA,
        NORMALIZED_JSONL,
        REPO_ROOT,
        SOURCES_YAML,
    )


QUOTA_EXIT_CODE: int = 3

logger = logging.getLogger("run_ingestion")


@dataclass(frozen=True)
class Step:
    name: str
    module: str               # e.g. "ingestion.normalize.parse_judgments"
    outputs: tuple[Path, ...]  # paths that must exist + be newer than inputs to skip
    inputs: tuple[Path, ...]   # paths whose mtime invalidates the outputs
    extra_args: tuple[str, ...] = ()


PIPELINE: list[Step] = [
    Step(
        name="verify_corpus",
        module="ingestion.collect.verify_corpus",
        outputs=(),  # no produced file; we always run this as a check
        inputs=(SOURCES_YAML,),
    ),
    Step(
        name="classify",
        module="ingestion.classify.run_classifier",
        outputs=(),  # writes back to sources.yaml; no separate file
        inputs=(SOURCES_YAML,),
    ),
    Step(
        name="normalize",
        module="ingestion.normalize.parse_judgments",
        outputs=(NORMALIZED_JSONL,),
        inputs=(SOURCES_YAML,),
    ),
    Step(
        name="chunk",
        module="ingestion.chunk.run_chunking",
        outputs=(CHUNKS_JSONL,),
        inputs=(NORMALIZED_JSONL, SOURCES_YAML),
    ),
    Step(
        name="embed",
        module="ingestion.embed.embed_chunks",
        outputs=(EMBEDDINGS_JSONL,),
        inputs=(CHUNKS_JSONL,),
    ),
    Step(
        name="build_bm25",
        module="ingestion.index.build_bm25",
        outputs=(BM25_CHUNK_IDS,),  # the directory contents are derived; sentinel is the ids file
        inputs=(CHUNKS_JSONL,),
    ),
    Step(
        name="build_chroma",
        module="ingestion.index.build_chroma",
        outputs=(CHROMA_DB_DIR,),
        inputs=(CHUNKS_JSONL, EMBEDDINGS_JSONL, SOURCES_YAML),
        extra_args=("--reset",),
    ),
    Step(
        name="verify_index",
        module="ingestion.index.verify_index",
        outputs=(),  # no produced file; this is a check
        inputs=(BM25_INDEX_DIR, CHROMA_DB_DIR),
    ),
]


def configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )


def is_step_up_to_date(step: Step) -> bool:
    """Return True if outputs exist and are at least as new as inputs.

    A step with no outputs (checker steps like verify_corpus and
    verify_index) is never considered up-to-date — those always run.

    The `embed` step needs an extra check on top of mtime: a quota stop
    leaves embeddings.jsonl on disk with fewer records than chunks.jsonl
    has chunks. Pure mtime would call that "done" even though it's only
    partial. We count lines and compare.
    """
    if not step.outputs:
        return False
    output_paths_exist = all(p.exists() for p in step.outputs)
    if not output_paths_exist:
        return False

    def newest_mtime(paths: tuple[Path, ...]) -> float:
        # For directories we use the directory mtime; for files, file mtime.
        # Either is a reasonable proxy: a newly-written directory bumps its mtime.
        return max((p.stat().st_mtime for p in paths if p.exists()), default=0.0)

    oldest_output = min(p.stat().st_mtime for p in step.outputs)
    newest_input = newest_mtime(step.inputs)
    if oldest_output < newest_input:
        return False

    if step.name == "embed":
        # Partial-progress detection: embed writes one record per chunk it
        # successfully embeds. If embeddings.jsonl has fewer records than
        # chunks.jsonl has chunks, the embed step stopped early (most
        # likely on quota) and needs to resume.
        try:
            chunks_count = _count_nonblank_lines(CHUNKS_JSONL)
            embeddings_count = _count_nonblank_lines(EMBEDDINGS_JSONL)
        except OSError:
            return False
        if embeddings_count < chunks_count:
            logger.info(
                "embed: %d embeddings / %d chunks — not complete, will re-run",
                embeddings_count, chunks_count,
            )
            return False

    return True


def _count_nonblank_lines(path: Path) -> int:
    count = 0
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                count += 1
    return count


def run_step(step: Step, dry_run: bool) -> tuple[int, float]:
    """Run a step as a subprocess. Returns (exit_code, duration_seconds)."""
    cmd = [sys.executable, "-m", step.module, *step.extra_args]
    logger.info("RUN  %s :  %s", step.name, " ".join(cmd))
    if dry_run:
        return 0, 0.0

    start = time.time()
    result = subprocess.run(cmd, cwd=str(REPO_ROOT))
    duration = time.time() - start
    return result.returncode, duration


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--force", action="store_true", help="Re-run every step regardless of staleness.")
    parser.add_argument("--from", dest="from_step", default=None, help="Start from this step name.")
    parser.add_argument("--skip", action="append", default=[], help="Step name(s) to skip entirely.")
    parser.add_argument("--dry-run", action="store_true", help="Print plan without executing.")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    configure_logging(args.verbose)

    step_names = [s.name for s in PIPELINE]
    if args.from_step and args.from_step not in step_names:
        logger.error("--from %s: unknown step. Known steps: %s", args.from_step, step_names)
        return 2
    for skip_name in args.skip:
        if skip_name not in step_names:
            logger.error("--skip %s: unknown step. Known steps: %s", skip_name, step_names)
            return 2

    INGESTION_DATA.mkdir(parents=True, exist_ok=True)

    started = False
    failures: list[str] = []
    skipped_up_to_date: list[str] = []
    skipped_by_flag: list[str] = []
    completed: list[tuple[str, float]] = []

    for step in PIPELINE:
        # Honour --from
        if args.from_step and not started:
            if step.name == args.from_step:
                started = True
            else:
                logger.info("SKIP %s (before --from)", step.name)
                continue
        if step.name in args.skip:
            logger.info("SKIP %s (--skip flag)", step.name)
            skipped_by_flag.append(step.name)
            continue
        if not args.force and is_step_up_to_date(step):
            logger.info("SKIP %s (up-to-date)", step.name)
            skipped_up_to_date.append(step.name)
            continue

        rc, dur = run_step(step, args.dry_run)
        if rc == QUOTA_EXIT_CODE:
            logger.warning(
                "STOP %s: quota exhausted (%.1fs). Re-run tomorrow to resume.",
                step.name, dur,
            )
            return QUOTA_EXIT_CODE
        if rc != 0:
            logger.error("FAIL %s: exit %d (%.1fs)", step.name, rc, dur)
            failures.append(step.name)
            # Continue or stop? For now: stop on first failure. Easier to debug.
            break
        if args.dry_run:
            logger.info("DRY  %s (would run)", step.name)
        else:
            logger.info("DONE %s (%.1fs)", step.name, dur)
        completed.append((step.name, dur))

    logger.info("=== pipeline summary ===")
    for name, dur in completed:
        logger.info("  DONE   %-15s  %.1fs", name, dur)
    for name in skipped_up_to_date:
        logger.info("  SKIP   %-15s  (up-to-date)", name)
    for name in skipped_by_flag:
        logger.info("  SKIP   %-15s  (--skip)", name)
    for name in failures:
        logger.info("  FAIL   %-15s", name)

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())