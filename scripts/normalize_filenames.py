"""Normalize corpus filenames per CORP-5 rules.

Expected layout:
  data/
    bns_2023.pdf            <- top-level bare-act PDFs (acts)
    ipc_1860.pdf
    bnss_2023.pdf
    01/                     <- numbered case folders (judgments)
      <html file>
      <pdf file>
    02/
      <html file>
      <pdf file>
    ...
    70/

Apply normalization to every PDF at the top level of data/ AND every
HTML/PDF inside data/<NN>/:
  - lowercase
  - spaces -> single underscore
  - punctuation removed: . , & ' " ( ) : ; ? ! / \\
  - multiple consecutive underscores collapsed to one
  - leading and trailing underscores stripped
  - file extension preserved (lowercased)

After renaming, verify each data/<NN>/ folder contains exactly one
HTML and one PDF with the same base name (the CORP-5 pairing rule).
Top-level act PDFs are NOT subject to pairing verification.

Usage:
  python scripts/normalize_filenames.py              # dry run, shows planned changes
  python scripts/normalize_filenames.py --apply      # actually rename
  python scripts/normalize_filenames.py --data-root /path/to/data --apply

Exit codes:
  0  all good (or dry run completed)
  1  pairing rule violated (HTML and PDF base names disagree, or counts wrong)
  2  filesystem error during rename
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path


PUNCTUATION_TO_STRIP = r"""[.,&'"():;?!/\\]"""
ALLOWED_EXTENSIONS = {".html", ".pdf"}
CASE_FOLDER_PATTERN = re.compile(r"^\d{2,}$")


@dataclass(frozen=True)
class RenamePlan:
    source: Path
    target: Path

    @property
    def is_noop(self) -> bool:
        return self.source == self.target


def normalize_filename(filename: str) -> str:
    stem, dot, ext = filename.rpartition(".")
    if not dot:
        return filename

    normalized = stem.lower()
    normalized = re.sub(PUNCTUATION_TO_STRIP, "", normalized)
    normalized = re.sub(r"\s+", "_", normalized)
    normalized = re.sub(r"_+", "_", normalized)
    normalized = normalized.strip("_")

    return f"{normalized}.{ext.lower()}"


def find_case_folders(data_root: Path) -> list[Path]:
    return sorted(
        path for path in data_root.iterdir()
        if path.is_dir() and CASE_FOLDER_PATTERN.match(path.name)
    )


def find_top_level_act_pdfs(data_root: Path) -> list[Path]:
    return sorted(
        path for path in data_root.iterdir()
        if path.is_file() and path.suffix.lower() == ".pdf"
    )


def find_files_to_rename(data_root: Path) -> list[Path]:
    files: list[Path] = list(find_top_level_act_pdfs(data_root))
    for case_folder in find_case_folders(data_root):
        for path in case_folder.iterdir():
            if path.is_file() and path.suffix.lower() in ALLOWED_EXTENSIONS:
                files.append(path)
    return files


def build_rename_plans(files: list[Path]) -> list[RenamePlan]:
    plans: list[RenamePlan] = []
    for source in files:
        normalized_name = normalize_filename(source.name)
        target = source.with_name(normalized_name)
        plans.append(RenamePlan(source=source, target=target))
    return plans


def detect_target_collisions(plans: list[RenamePlan]) -> list[tuple[Path, list[Path]]]:
    by_target: dict[Path, list[Path]] = defaultdict(list)
    for plan in plans:
        by_target[plan.target].append(plan.source)

    collisions: list[tuple[Path, list[Path]]] = []
    for target, sources in by_target.items():
        if len(sources) > 1:
            collisions.append((target, sources))
    return collisions


def verify_pairing(data_root: Path) -> list[str]:
    errors: list[str] = []

    for case_folder in find_case_folders(data_root):
        html_files = [p for p in case_folder.iterdir() if p.suffix.lower() == ".html"]
        pdf_files = [p for p in case_folder.iterdir() if p.suffix.lower() == ".pdf"]

        rel = case_folder.relative_to(data_root)

        if len(html_files) != 1:
            errors.append(f"{rel}: expected exactly 1 HTML, found {len(html_files)}")
            continue
        if len(pdf_files) != 1:
            errors.append(f"{rel}: expected exactly 1 PDF, found {len(pdf_files)}")
            continue

        html_stem = html_files[0].stem
        pdf_stem = pdf_files[0].stem
        if html_stem != pdf_stem:
            errors.append(
                f"{rel}: HTML base name '{html_stem}' does not match PDF base name '{pdf_stem}'"
            )

    return errors


def print_plans(plans: list[RenamePlan], data_root: Path) -> tuple[int, int]:
    rename_count = 0
    noop_count = 0
    for plan in plans:
        rel_source = plan.source.relative_to(data_root)
        if plan.is_noop:
            noop_count += 1
            print(f"  [skip] {rel_source} (already normalized)")
        else:
            rename_count += 1
            print(f"  [rename] {rel_source}")
            print(f"        -> {plan.target.name}")
    return rename_count, noop_count


def apply_plans(plans: list[RenamePlan], data_root: Path) -> int:
    applied = 0
    for plan in plans:
        if plan.is_noop:
            continue
        if plan.target.exists() and plan.target != plan.source:
            print(
                f"  [error] target already exists: {plan.target.relative_to(data_root)}",
                file=sys.stderr,
            )
            return -1
        plan.source.rename(plan.target)
        applied += 1
    return applied


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--data-root",
        type=Path,
        default=Path("data"),
        help="Path to the data directory (default: ./data)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually rename files. Without this flag, runs as dry run.",
    )
    parser.add_argument(
        "--skip-pairing-check",
        action="store_true",
        help="Skip the HTML/PDF pairing verification (not recommended).",
    )
    args = parser.parse_args()

    data_root: Path = args.data_root.resolve()
    if not data_root.is_dir():
        print(f"error: data root does not exist: {data_root}", file=sys.stderr)
        return 2

    case_folders = find_case_folders(data_root)
    act_pdfs = find_top_level_act_pdfs(data_root)

    if not case_folders and not act_pdfs:
        print(
            f"No numbered case folders (01, 02, ...) or top-level PDFs found in {data_root}",
            file=sys.stderr,
        )
        return 2

    print(f"Scanning {data_root}...")
    if act_pdfs:
        print(f"Found {len(act_pdfs)} top-level act PDF(s).")
    if case_folders:
        print(f"Found {len(case_folders)} case folders: "
              f"{case_folders[0].name} ... {case_folders[-1].name}")

    files = find_files_to_rename(data_root)
    if not files:
        print("No HTML or PDF files found inside case folders.")
        return 0

    print(f"Found {len(files)} files to consider.\n")

    plans = build_rename_plans(files)

    collisions = detect_target_collisions(plans)
    if collisions:
        print("ERROR: target filename collisions detected:", file=sys.stderr)
        for target, sources in collisions:
            print(f"  {target.relative_to(data_root)} would be produced by:", file=sys.stderr)
            for src in sources:
                print(f"    - {src.relative_to(data_root)}", file=sys.stderr)
        print(
            "\nResolve by manually renaming one of the source files to disambiguate, then re-run.",
            file=sys.stderr,
        )
        return 2

    if args.apply:
        print("APPLYING renames...\n")
    else:
        print("DRY RUN. Re-run with --apply to actually rename.\n")

    rename_count, noop_count = print_plans(plans, data_root)

    print()
    print(f"Summary: {rename_count} to rename, {noop_count} already normalized.")

    if args.apply:
        applied = apply_plans(plans, data_root)
        if applied < 0:
            return 2
        print(f"\nRenamed {applied} files.")

    if not args.skip_pairing_check:
        print("\nVerifying HTML/PDF pairing in each case folder...")
        if not args.apply:
            print("  (note: pairing check runs against current filenames; re-run after --apply)")
        errors = verify_pairing(data_root)
        if errors:
            print("\nPAIRING ERRORS:", file=sys.stderr)
            for err in errors:
                print(f"  {err}", file=sys.stderr)
            return 1
        else:
            print("  all case folders have a paired HTML + PDF with matching base names.")

    return 0


if __name__ == "__main__":
    sys.exit(main())