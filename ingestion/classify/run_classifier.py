"""Orchestrate relevance classification of all pending judgments.

Reads sources.yaml, iterates judgments with status='pending' (or all of them
if --force is passed), invokes the Gemini classifier for each, and persists
the verdict back to sources.yaml.

The Gemini free tier limits to 15 requests per minute (per-minute rate) and
a low daily quota (currently ~20 requests per day per model — Google adjusts
this periodically). The orchestrator sleeps 4.5 seconds between calls to
stay under the per-minute limit, and stops cleanly when the daily quota is
exhausted so it can be resumed after midnight Pacific time.

Status assignments:
  score >= APPROVE_THRESHOLD (0.6)    -> approved
  score >= REVIEW_THRESHOLD (0.4)     -> needs-review
  score <  REVIEW_THRESHOLD           -> rejected
  classifier failure (non-quota)       -> needs-review with error in manual_review_notes
  quota-exhausted failure              -> entry stays 'pending' for next run

Usage:
  GEMINI_API_KEY=... python ingestion/classify/run_classifier.py
  GEMINI_API_KEY=... python ingestion/classify/run_classifier.py --force
  GEMINI_API_KEY=... python ingestion/classify/run_classifier.py --dry-run
  GEMINI_API_KEY=... python ingestion/classify/run_classifier.py --only 01,03

Exit codes:
  0  all pending judgments classified (or dry run completed)
  1  one or more non-quota classification failures
  2  configuration error (missing API key, manifest not found, etc.)
  3  daily Gemini quota exhausted; re-run after midnight Pacific to resume
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

import yaml

try:
    from ingestion.classify.relevance_classifier import (
        ClassificationFailure,
        ClassifierVerdict,
        JudgmentContext,
        classify_judgment_html,
    )
    from ingestion.collect.schema import JudgmentManifestEntry, RelevanceStatus, SourcesManifest
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from ingestion.classify.relevance_classifier import (
        ClassificationFailure,
        ClassifierVerdict,
        JudgmentContext,
        classify_judgment_html,
    )
    from ingestion.collect.schema import JudgmentManifestEntry, RelevanceStatus, SourcesManifest


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = REPO_ROOT / "sources.yaml"
DEFAULT_DATA_ROOT = REPO_ROOT / "data"

APPROVE_THRESHOLD: float = 0.6
REVIEW_THRESHOLD: float = 0.4

SECONDS_BETWEEN_CALLS: float = 4.5

# Quota-exhaustion fingerprints in classifier failure reason strings. When any
# of these appear in a failure, the daily Gemini free-tier quota is exhausted
# and further calls today will only burn through more 429 responses. The
# orchestrator stops cleanly, leaves the entry in 'pending' state for the next
# run, and exits with a distinct code so callers can distinguish quota stops
# from genuine classification failures.
QUOTA_EXHAUSTED_FINGERPRINTS: tuple[str, ...] = (
    "RESOURCE_EXHAUSTED",
    "429",
    "exceeded your current quota",
)

QUOTA_EXHAUSTED_EXIT_CODE: int = 3

logger = logging.getLogger("classifier")


def is_quota_exhausted(error_note: str) -> bool:
    return any(token in error_note for token in QUOTA_EXHAUSTED_FINGERPRINTS)


def configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )


def select_judgments_to_classify(
    manifest: SourcesManifest, force: bool, only_folders: set[str] | None
) -> list[JudgmentManifestEntry]:
    candidates = manifest.judgments
    if only_folders is not None:
        candidates = [j for j in candidates if j.folder in only_folders]
    if not force:
        candidates = [j for j in candidates if j.relevance_classifier_status == RelevanceStatus.PENDING]
    return candidates


def derive_status(score: float) -> RelevanceStatus:
    if score >= APPROVE_THRESHOLD:
        return RelevanceStatus.APPROVED
    if score >= REVIEW_THRESHOLD:
        return RelevanceStatus.NEEDS_REVIEW
    return RelevanceStatus.REJECTED


def classify_one(
    entry: JudgmentManifestEntry, data_root: Path, api_key: str
) -> tuple[RelevanceStatus, float | None, str | None, str | None]:
    context = JudgmentContext(
        case_name=entry.case_name,
        citation=entry.citation,
        court=entry.court,
        year=entry.year,
        primary_section=entry.primary_section,
        html_path=entry.html_path(data_root),
    )
    result = classify_judgment_html(context, api_key=api_key)

    if isinstance(result, ClassificationFailure):
        return (
            RelevanceStatus.NEEDS_REVIEW,
            None,
            None,
            f"classifier failure: {result.reason}",
        )

    assert isinstance(result, ClassifierVerdict)
    new_status = derive_status(result.relevance_score)
    return (new_status, result.relevance_score, result.reasoning, None)


def update_yaml_in_place(
    manifest_path: Path, updates: dict[str, dict[str, Any]]
) -> None:
    raw = yaml.safe_load(manifest_path.read_text())
    for judgment in raw.get("judgments", []):
        folder = judgment.get("folder")
        if folder in updates:
            for field, value in updates[folder].items():
                judgment[field] = value
    manifest_path.write_text(
        yaml.safe_dump(raw, sort_keys=False, allow_unicode=True, width=120)
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-classify entries even if already scored. Default: only pending entries.",
    )
    parser.add_argument(
        "--only",
        type=str,
        default=None,
        help="Comma-separated folder numbers to classify (e.g. '01,03,07').",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be classified without calling Gemini or writing the manifest.",
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    configure_logging(args.verbose)

    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not args.dry_run and not api_key:
        logger.error("GEMINI_API_KEY environment variable is required (or use --dry-run).")
        return 2

    manifest_path: Path = args.manifest.resolve()
    data_root: Path = args.data_root.resolve()
    if not manifest_path.is_file():
        logger.error("Manifest not found at %s", manifest_path)
        return 2

    raw = yaml.safe_load(manifest_path.read_text())
    try:
        manifest = SourcesManifest.model_validate(raw)
    except Exception as e:
        logger.error("Manifest failed schema validation: %s", e)
        return 2

    only_folders: set[str] | None = None
    if args.only:
        only_folders = {f.strip() for f in args.only.split(",") if f.strip()}

    to_classify = select_judgments_to_classify(manifest, args.force, only_folders)

    if not to_classify:
        logger.info("Nothing to classify. (Use --force to re-classify already-scored entries.)")
        return 0

    logger.info("Will classify %d judgment(s).", len(to_classify))
    if args.dry_run:
        for entry in to_classify:
            logger.info(
                "  [dry-run] folder %s: %s (currently %s)",
                entry.folder, entry.case_id, entry.relevance_classifier_status.value,
            )
        return 0

    updates: dict[str, dict[str, Any]] = {}
    failures = 0
    quota_exhausted = False
    processed_count = 0

    for index, entry in enumerate(to_classify):
        logger.info(
            "[%d/%d] classifying folder %s: %s ...",
            index + 1, len(to_classify), entry.folder, entry.case_id,
        )
        new_status, score, reasoning, error_note = classify_one(entry, data_root, api_key)

        if error_note is not None:
            if is_quota_exhausted(error_note):
                logger.warning(
                    "  QUOTA EXHAUSTED on folder %s. Stopping batch run.",
                    entry.folder,
                )
                logger.warning(
                    "  Gemini's daily free-tier quota has been hit. The current "
                    "entry remains 'pending' and will be retried on the next run "
                    "(quotas reset at midnight Pacific time)."
                )
                quota_exhausted = True
                break

            logger.warning("  FAILED: %s", error_note)
            failures += 1
            updates[entry.folder] = {
                "relevance_classifier_status": new_status.value,
                "manual_review_notes": (
                    f"{entry.manual_review_notes} | " if entry.manual_review_notes else ""
                ) + error_note,
            }
        else:
            logger.info("  -> score=%.2f status=%s", score, new_status.value)
            updates[entry.folder] = {
                "relevance_classifier_status": new_status.value,
                "relevance_score": score,
                "classifier_reasoning": reasoning,
            }

        processed_count += 1
        if index < len(to_classify) - 1:
            time.sleep(SECONDS_BETWEEN_CALLS)

    if updates:
        update_yaml_in_place(manifest_path, updates)

    if quota_exhausted:
        remaining = len(to_classify) - processed_count
        logger.info(
            "Wrote %d update(s) to %s. Stopped early due to quota. "
            "Successful classifications: %d. Remaining to classify: %d. "
            "Re-run after quota resets to continue from where we left off.",
            len(updates), manifest_path, len(updates) - failures, remaining,
        )
        return QUOTA_EXHAUSTED_EXIT_CODE

    logger.info(
        "Wrote %d update(s) to %s. Failures: %d.",
        len(updates), manifest_path, failures,
    )

    return 1 if failures > 0 else 0


if __name__ == "__main__":
    sys.exit(main())