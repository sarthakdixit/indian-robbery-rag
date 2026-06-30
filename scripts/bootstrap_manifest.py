"""Bootstrap a draft sources.yaml from what's actually on disk.

Scans data/<NN>/ for each numbered folder, identifies the HTML and PDF
inside, and emits a draft manifest entry with filename fields populated
and legal-metadata fields set to TODO placeholders.

IMPORTANT: Run scripts/normalize_filenames.py --apply FIRST. The Pydantic
schema requires lowercase-snake filenames per CORP-5; this helper records
whatever names are on disk, so if they aren't normalized yet, the draft
won't pass schema validation. The helper warns about non-normalized
filenames it finds and exits non-zero if any are present.

Output: sources.yaml.draft (next to the existing sources.yaml). The
existing manifest is NOT modified. Acts section is preserved from the
existing manifest if present.

You then:
  1. Open sources.yaml.draft and fill in case_name / citation / court /
     year / primary_section / outcome / indian_kanoon_url for each
     folder where the field shows TODO.
  2. Move sources.yaml.draft -> sources.yaml (or selectively merge).
  3. Run ingestion/collect/verify_corpus.py --write-hashes.

Usage:
  python scripts/normalize_filenames.py --apply    # do this FIRST
  python scripts/bootstrap_manifest.py             # then this
  python scripts/bootstrap_manifest.py --data-root data --output sources.yaml.draft

Exit codes:
  0  draft written, no issues
  1  pairing issues, non-normalized filenames, or other warnings — review draft
  2  configuration error (data root missing, etc.)
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA_ROOT = REPO_ROOT / "data"
DEFAULT_EXISTING_MANIFEST = REPO_ROOT / "sources.yaml"
DEFAULT_OUTPUT = REPO_ROOT / "sources.yaml.draft"

FOLDER_NUMBER_RE = re.compile(r"^\d{2,}$")
NUMERIC_STEM_RE = re.compile(r"^\d+$")
YEAR_IN_FILENAME_RE = re.compile(r"(?<!\d)(18[6-9]\d|19\d{2}|20\d{2})(?!\d)")
NORMALIZED_FILENAME_RE = re.compile(r"^[a-z0-9_]+\.(html|pdf)$")


def is_normalized(filename: str) -> bool:
    return bool(NORMALIZED_FILENAME_RE.match(filename))


@dataclass
class FolderScan:
    folder: str
    html_files: list[Path] = field(default_factory=list)
    pdf_files: list[Path] = field(default_factory=list)
    other_files: list[Path] = field(default_factory=list)

    @property
    def pair_ok(self) -> bool:
        return len(self.html_files) == 1 and len(self.pdf_files) == 1

    @property
    def html_stem(self) -> str | None:
        return self.html_files[0].stem if self.html_files else None

    @property
    def pdf_stem(self) -> str | None:
        return self.pdf_files[0].stem if self.pdf_files else None


def scan_folder(folder_path: Path) -> FolderScan:
    scan = FolderScan(folder=folder_path.name)
    for child in folder_path.iterdir():
        if not child.is_file():
            continue
        suffix = child.suffix.lower()
        if suffix == ".html":
            scan.html_files.append(child)
        elif suffix == ".pdf":
            scan.pdf_files.append(child)
        else:
            scan.other_files.append(child)
    return scan


def find_numbered_folders(data_root: Path) -> list[Path]:
    return sorted(
        d for d in data_root.iterdir()
        if d.is_dir() and FOLDER_NUMBER_RE.match(d.name)
    )


def guess_case_name_from_stem(stem: str) -> str:
    if NUMERIC_STEM_RE.match(stem):
        return "TODO: case name (HTML filename was a numeric document ID)"
    cleaned = stem.replace("_", " ")
    cleaned = re.sub(r"\s+vs\s+", " v. ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(
        r"[\s,]+on\s+\d{1,2}[\s,]+\w+[\s,]+\d{4}\s*$",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"\s+\d{4}\s*$", "", cleaned)
    cleaned = cleaned.strip(" ,.;")
    return " ".join(word.capitalize() if word.lower() != "v." else "v." for word in cleaned.split())


def guess_year_from_stem(stem: str) -> int | None:
    matches = YEAR_IN_FILENAME_RE.findall(stem)
    if not matches:
        return None
    return int(matches[-1])


def extract_indian_kanoon_doc_id(stems: list[str]) -> str | None:
    for stem in stems:
        if NUMERIC_STEM_RE.match(stem):
            return stem
    return None


def build_judgment_entry(scan: FolderScan, today: date) -> dict:
    html_stem = scan.html_stem
    pdf_stem = scan.pdf_stem
    candidate_stems = [s for s in [html_stem, pdf_stem] if s is not None]

    primary_stem = html_stem or pdf_stem or "unknown"
    case_name_guess = guess_case_name_from_stem(primary_stem)
    year_guess = guess_year_from_stem(primary_stem)
    doc_id_guess = extract_indian_kanoon_doc_id(candidate_stems)

    case_id = re.sub(r"[^a-z0-9_]+", "_", primary_stem.lower()).strip("_")
    case_id = case_id[:100] if case_id else f"folder_{scan.folder}"

    html_filename = scan.html_files[0].name if scan.html_files else "todo_missing.html"
    pdf_filename = scan.pdf_files[0].name if scan.pdf_files else "todo_missing.pdf"

    return {
        "folder": scan.folder,
        "case_id": case_id,
        "case_name": case_name_guess if not case_name_guess.startswith("TODO") else case_name_guess,
        "citation": "TODO: citation (e.g., '(2007) 12 SCC 641 / AIR 2007 SC 3234')",
        "court": "TODO: Supreme Court of India | Delhi High Court | ...",
        "year": year_guess if year_guess else today.year,
        "primary_section": "TODO: e.g. '397 IPC' or '309 BNS'",
        "other_sections": [],
        "outcome": "other",
        "indian_kanoon_url": (
            f"https://indiankanoon.org/doc/{doc_id_guess}/"
            if doc_id_guess
            else "TODO: https://indiankanoon.org/doc/<id>/"
        ),
        "indian_kanoon_doc_id": doc_id_guess,
        "html_filename": html_filename,
        "pdf_filename": pdf_filename,
        "retrieved_date": today.isoformat(),
        "html_sha256": None,
        "pdf_sha256": None,
        "relevance_classifier_status": "pending",
        "relevance_score": None,
        "classifier_reasoning": None,
        "manual_review_notes": None,
    }


def load_existing_acts(manifest_path: Path) -> tuple[list[dict], str]:
    if not manifest_path.is_file():
        return [], "2026.05.14"
    try:
        raw = yaml.safe_load(manifest_path.read_text())
    except yaml.YAMLError:
        return [], "2026.05.14"
    acts = raw.get("acts", []) if isinstance(raw, dict) else []
    version = raw.get("corpus_version", "2026.05.14") if isinstance(raw, dict) else "2026.05.14"
    return acts, version


def write_draft_with_comments(
    output_path: Path,
    corpus_version: str,
    acts: list[dict],
    judgments: list[dict],
    scans: dict[str, FolderScan],
) -> None:
    lines: list[str] = [
        "# sources.yaml.draft — bootstrapped from on-disk folders",
        "#",
        "# Generated by scripts/bootstrap_manifest.py. Filename fields are",
        "# populated from what was found in data/<NN>/. Legal-metadata fields",
        "# (case_name, citation, court, year, primary_section, outcome,",
        "# indian_kanoon_url) are TODO placeholders for you to fill in.",
        "#",
        "# Heuristics applied:",
        "#   - case_name guessed from the HTML filename stem (replaces underscores,",
        "#     normalizes 'vs' to 'v.', strips trailing dates)",
        "#   - year guessed from a 4-digit year in the filename; if none found,",
        f"#     defaults to {date.today().year} (current year) as a visible signal",
        "#     that the year needs human verification",
        "#   - indian_kanoon_doc_id and URL auto-filled when the PDF filename is",
        "#     a numeric Indian Kanoon document ID",
        "#",
        "# When complete:",
        "#   1. Verify every TODO is replaced with real metadata",
        "#   2. mv sources.yaml.draft sources.yaml",
        "#   3. python ingestion/collect/verify_corpus.py --write-hashes",
        "#   4. python ingestion/classify/run_classifier.py",
        "",
        f'corpus_version: "{corpus_version}"',
        'schema_version: "1"',
        "",
        "acts:",
    ]

    if acts:
        acts_yaml = yaml.safe_dump(
            acts, sort_keys=False, allow_unicode=True, width=120, default_flow_style=False
        )
        for ln in acts_yaml.splitlines():
            lines.append("  " + ln if ln else "")
    else:
        lines.append("  []  # TODO: re-add bare-act entries from your prior sources.yaml")

    lines.append("")
    lines.append("judgments:")

    for j in judgments:
        scan = scans.get(j["folder"])
        if scan and not scan.pair_ok:
            lines.append(
                f"  # WARNING folder {j['folder']}: pairing issue "
                f"({len(scan.html_files)} HTML, {len(scan.pdf_files)} PDF) — fix before classifier runs"
            )
        if scan and scan.other_files:
            other_names = ", ".join(p.name for p in scan.other_files[:3])
            lines.append(
                f"  # NOTE folder {j['folder']}: other files present and will be ignored: {other_names}"
            )

        entry_yaml = yaml.safe_dump(
            [j], sort_keys=False, allow_unicode=True, width=120, default_flow_style=False
        )
        for ln in entry_yaml.splitlines():
            lines.append("  " + ln if ln else "")

    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--existing-manifest", type=Path, default=DEFAULT_EXISTING_MANIFEST)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    data_root: Path = args.data_root.resolve()
    output_path: Path = args.output.resolve()
    existing_manifest: Path = args.existing_manifest.resolve()

    if not data_root.is_dir():
        print(f"error: data root not found at {data_root}", file=sys.stderr)
        return 2

    folders = find_numbered_folders(data_root)
    if not folders:
        print(f"error: no numbered folders found under {data_root}", file=sys.stderr)
        return 2

    print(f"Scanning {len(folders)} folders under {data_root}...")

    today = date.today()
    scans: dict[str, FolderScan] = {}
    judgments: list[dict] = []
    pairing_issues = 0
    folders_with_extras = 0
    non_normalized_files = 0

    for folder_path in folders:
        scan = scan_folder(folder_path)
        scans[scan.folder] = scan

        if not scan.pair_ok:
            pairing_issues += 1
        if scan.other_files:
            folders_with_extras += 1

        for f in [*scan.html_files, *scan.pdf_files]:
            if not is_normalized(f.name):
                non_normalized_files += 1

        judgments.append(build_judgment_entry(scan, today))

    existing_acts, corpus_version = load_existing_acts(existing_manifest)
    write_draft_with_comments(output_path, corpus_version, existing_acts, judgments, scans)

    print()
    print(f"Wrote {output_path}")
    print(f"  folders scanned: {len(folders)}")
    print(f"  acts preserved: {len(existing_acts)}")
    print(f"  judgment entries drafted: {len(judgments)}")
    print(f"  folders with pairing issues: {pairing_issues}")
    print(f"  folders with extra files: {folders_with_extras}")
    print(f"  non-normalized filenames found: {non_normalized_files}")
    print()
    if non_normalized_files > 0:
        print(
            f"WARNING: {non_normalized_files} filenames are not in lowercase-snake form. "
            "The draft will not pass schema validation until you run:"
        )
        print("    python scripts/normalize_filenames.py --apply")
        print("Then re-run this script to regenerate the draft with normalized names.")
        print()
    print("Next steps:")
    if non_normalized_files > 0:
        print("  1. python scripts/normalize_filenames.py --apply")
        print("  2. python scripts/bootstrap_manifest.py  (re-run after normalization)")
        print(f"  3. Open {output_path.name} and replace every 'TODO:' with real metadata.")
        print(f"  4. mv {output_path.name} sources.yaml")
        print("  5. python ingestion/collect/verify_corpus.py --write-hashes")
    else:
        print(f"  1. Open {output_path.name} and replace every 'TODO:' with real metadata.")
        print(f"  2. mv {output_path.name} sources.yaml")
        print("  3. python ingestion/collect/verify_corpus.py --write-hashes")

    return 1 if (pairing_issues > 0 or non_normalized_files > 0) else 0


if __name__ == "__main__":
    sys.exit(main())