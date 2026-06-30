"""Normalize the corpus into structured JSONL.

Reads sources.yaml; for every approved judgment runs the HTML extractor;
for every act runs the PDF parser. Writes one JSON line per document to
the normalized output file. Logs warnings inline and aggregates them in
the per-document `parse_warnings` field.

Output: one JSONL file with mixed NormalizedAct and NormalizedJudgment
records, discriminated by the `source_type` field.

Usage:
  python ingestion/normalize/parse_judgments.py
  python ingestion/normalize/parse_judgments.py --output ingestion/data/normalized.jsonl
  python ingestion/normalize/parse_judgments.py --only-judgments
  python ingestion/normalize/parse_judgments.py --only-acts
  python ingestion/normalize/parse_judgments.py --include-pending

Exit codes:
  0  normalization completed (warnings may have been logged)
  1  one or more documents failed to normalize (no paragraphs / no sections)
  2  configuration error (manifest missing, etc.)
"""

from __future__ import annotations

import argparse
import logging
import sys
import traceback
from pathlib import Path

import yaml

try:
    from ingestion.collect.schema import (
        ActManifestEntry,
        JudgmentManifestEntry,
        SourcesManifest,
    )
    from ingestion.normalize.clean_html import extract_judgment
    from ingestion.normalize.parse_acts_pdf import parse_act_pdf
    from ingestion.normalize.schema import (
        ActSection,
        JudgmentParagraph,
        NormalizedAct,
        NormalizedJudgment,
    )
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from ingestion.collect.schema import (
        ActManifestEntry,
        JudgmentManifestEntry,
        SourcesManifest,
    )
    from ingestion.normalize.clean_html import extract_judgment
    from ingestion.normalize.parse_acts_pdf import parse_act_pdf
    from ingestion.normalize.schema import (
        ActSection,
        JudgmentParagraph,
        NormalizedAct,
        NormalizedJudgment,
    )


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = REPO_ROOT / "sources.yaml"
DEFAULT_DATA_ROOT = REPO_ROOT / "data"
DEFAULT_OUTPUT = REPO_ROOT / "ingestion" / "data" / "normalized.jsonl"

logger = logging.getLogger("normalize")


def configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )


def normalize_act(entry: ActManifestEntry, data_root: Path) -> tuple[NormalizedAct | None, bool]:
    pdf_path = data_root / entry.filename
    logger.info("act %s: parsing %s", entry.short_name, pdf_path.name)
    result = parse_act_pdf(pdf_path)

    for w in result.warnings:
        logger.warning("act %s: %s", entry.short_name, w)

    if not result.sections:
        logger.error("act %s: 0 sections extracted — skipping", entry.short_name)
        return None, False

    sections = [
        ActSection(
            section_number=s.number,
            heading=s.heading or None,
            text=s.text,
            chapter=s.chapter,
            chapter_number=s.chapter_number,
        )
        for s in result.sections
    ]
    act = NormalizedAct(
        act_id=entry.act_id,
        act_name=entry.act_name,
        short_name=entry.short_name,
        source_url=entry.source_url,
        pdf_filename=entry.filename,
        sections=sections,
        parse_warnings=result.warnings,
    )
    logger.info("act %s: %d sections extracted", entry.short_name, len(sections))
    return act, True


def normalize_judgment(
    entry: JudgmentManifestEntry, data_root: Path
) -> tuple[NormalizedJudgment | None, bool]:
    html_path = entry.html_path(data_root)
    logger.info("judgment %s: extracting %s", entry.folder, html_path.name)
    try:
        result = extract_judgment(html_path)
    except Exception as e:
        # bs4/lxml occasionally crashes on malformed Indian Kanoon HTML in
        # ways that surface as AttributeError, TypeError, or ValueError. One
        # bad file should not abort the whole normalize run; the failure is
        # logged with full traceback and the judgment is skipped so subsequent
        # entries still get processed. This judgment will be missing from
        # normalized.jsonl until either the HTML is replaced or the parser
        # is patched to handle the case.
        logger.error(
            "judgment %s: parser crashed (%s: %s) — skipping",
            entry.folder, type(e).__name__, e,
        )
        logger.error("judgment %s: full traceback:\n%s", entry.folder, traceback.format_exc())
        return None, False

    for w in result.warnings:
        logger.warning("judgment %s: %s", entry.folder, w)

    if not result.paragraphs:
        logger.error("judgment %s: 0 paragraphs extracted — skipping", entry.folder)
        return None, False

    paragraphs = [
        JudgmentParagraph(paragraph_index=i, text=p) for i, p in enumerate(result.paragraphs)
    ]
    judgment = NormalizedJudgment(
        folder=entry.folder,
        case_id=entry.case_id,
        case_name=entry.case_name,
        citation=entry.citation,
        court=entry.court,
        year=entry.year,
        primary_section=entry.primary_section,
        other_sections=entry.other_sections,
        outcome=entry.outcome.value,
        indian_kanoon_url=entry.indian_kanoon_url,
        pdf_filename=entry.pdf_filename,
        html_filename=entry.html_filename,
        paragraphs=paragraphs,
        parse_warnings=result.warnings,
    )
    logger.info("judgment %s: %d paragraphs extracted", entry.folder, len(paragraphs))
    return judgment, True


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--only-acts", action="store_true", help="Skip judgments, only parse acts.")
    parser.add_argument(
        "--only-judgments", action="store_true", help="Skip acts, only parse judgments."
    )
    parser.add_argument(
        "--include-pending",
        action="store_true",
        help="Include judgments that have not yet been classified. Default: approved only.",
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    configure_logging(args.verbose)

    if args.only_acts and args.only_judgments:
        logger.error("--only-acts and --only-judgments are mutually exclusive.")
        return 2

    manifest_path: Path = args.manifest.resolve()
    data_root: Path = args.data_root.resolve()
    output_path: Path = args.output.resolve()

    if not manifest_path.is_file():
        logger.error("manifest not found at %s", manifest_path)
        return 2
    if not data_root.is_dir():
        logger.error("data root not found at %s", data_root)
        return 2

    raw = yaml.safe_load(manifest_path.read_text())
    try:
        manifest = SourcesManifest.model_validate(raw)
    except Exception as e:
        logger.error("manifest failed schema validation: %s", e)
        return 2

    output_path.parent.mkdir(parents=True, exist_ok=True)

    records_written = 0
    failures = 0

    with output_path.open("w", encoding="utf-8") as out:
        if not args.only_judgments:
            for act in manifest.acts:
                doc, ok = normalize_act(act, data_root)
                if doc is None or not ok:
                    failures += 1
                    continue
                out.write(doc.model_dump_json() + "\n")
                records_written += 1

        if not args.only_acts:
            judgments_to_process = (
                manifest.judgments
                if args.include_pending
                else manifest.approved_judgments()
            )
            if not judgments_to_process:
                logger.warning(
                    "no approved judgments to normalize "
                    "(run ingestion/classify/run_classifier.py first, or pass --include-pending)"
                )
            for judgment in judgments_to_process:
                doc, ok = normalize_judgment(judgment, data_root)
                if doc is None or not ok:
                    failures += 1
                    continue
                out.write(doc.model_dump_json() + "\n")
                records_written += 1

    logger.info("wrote %d records to %s; failures: %d", records_written, output_path, failures)
    return 1 if failures > 0 else 0


if __name__ == "__main__":
    sys.exit(main())