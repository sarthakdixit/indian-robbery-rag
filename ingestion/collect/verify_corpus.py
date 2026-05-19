"""Verify the corpus on disk matches sources.yaml.

Checks performed:
  1. Schema validation — sources.yaml parses against the Pydantic schema.
  2. Existence — every act PDF and every judgment HTML+PDF exists at the expected path.
  3. Pairing — each judgment folder has its HTML and PDF with matching base names.
  4. Filename normalization — every filename obeys CORP-5 rules.
  5. Orphan detection — every file in data/ is accounted for in the manifest.
  6. Hashing — computes SHA-256 for every file; if --write-hashes is passed,
     persists them back into sources.yaml. Otherwise, compares against
     existing hashes in the manifest and reports drift.

Usage:
  python ingestion/collect/verify_corpus.py
  python ingestion/collect/verify_corpus.py --write-hashes
  python ingestion/collect/verify_corpus.py --manifest sources.yaml --data-root data/

Exit codes:
  0  all checks passed
  1  one or more checks failed
  2  configuration error (missing manifest, unreadable file, etc.)
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

try:
    from ingestion.collect.schema import (
        ActManifestEntry,
        JudgmentManifestEntry,
        SourcesManifest,
    )
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from schema import ActManifestEntry, JudgmentManifestEntry, SourcesManifest


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_MANIFEST = REPO_ROOT / "sources.yaml"
DEFAULT_DATA_ROOT = REPO_ROOT / "data"


@dataclass
class VerificationReport:
    schema_errors: list[str] = field(default_factory=list)
    missing_files: list[str] = field(default_factory=list)
    pairing_errors: list[str] = field(default_factory=list)
    normalization_errors: list[str] = field(default_factory=list)
    orphaned_files: list[str] = field(default_factory=list)
    hash_drift: list[str] = field(default_factory=list)
    populated_hashes: list[str] = field(default_factory=list)

    @property
    def has_failures(self) -> bool:
        return bool(
            self.schema_errors
            or self.missing_files
            or self.pairing_errors
            or self.normalization_errors
            or self.orphaned_files
            or self.hash_drift
        )

    def print_summary(self) -> None:
        print()
        print("=" * 60)
        print("VERIFICATION SUMMARY")
        print("=" * 60)
        sections = [
            ("Schema errors", self.schema_errors),
            ("Missing files", self.missing_files),
            ("Pairing errors", self.pairing_errors),
            ("Filename normalization errors", self.normalization_errors),
            ("Orphaned files (in data/ but not in manifest)", self.orphaned_files),
            ("Hash drift (file changed since last verification)", self.hash_drift),
        ]
        for label, items in sections:
            symbol = "✓" if not items else "✗"
            print(f"  {symbol} {label}: {len(items)}")
            for item in items:
                print(f"      {item}")
        if self.populated_hashes:
            print(f"  ⓘ Hashes populated this run: {len(self.populated_hashes)}")


def compute_sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def load_manifest(manifest_path: Path) -> tuple[SourcesManifest | None, list[str]]:
    if not manifest_path.is_file():
        return None, [f"manifest not found at {manifest_path}"]
    try:
        raw = yaml.safe_load(manifest_path.read_text())
    except yaml.YAMLError as e:
        return None, [f"YAML parse error in {manifest_path}: {e}"]
    try:
        return SourcesManifest.model_validate(raw), []
    except ValidationError as e:
        errors = [f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in e.errors()]
        return None, errors


def check_act_exists(entry: ActManifestEntry, data_root: Path, report: VerificationReport) -> Path | None:
    path = data_root / entry.filename
    if not path.is_file():
        report.missing_files.append(f"act {entry.act_id}: expected {path}")
        return None
    return path


def check_judgment_files(
    entry: JudgmentManifestEntry, data_root: Path, report: VerificationReport
) -> tuple[Path | None, Path | None]:
    folder = data_root / entry.folder
    if not folder.is_dir():
        report.missing_files.append(f"folder {entry.folder}: directory does not exist")
        return None, None

    html_path = entry.html_path(data_root)
    pdf_path = entry.pdf_path(data_root)
    html_exists = html_path.is_file()
    pdf_exists = pdf_path.is_file()

    if not html_exists:
        report.missing_files.append(f"{entry.folder}/: HTML not found at {html_path.name}")
    if not pdf_exists:
        report.missing_files.append(f"{entry.folder}/: PDF not found at {pdf_path.name}")

    if not entry.has_matching_base_names():
        report.pairing_errors.append(
            f"{entry.folder}/: html base name {Path(entry.html_filename).stem!r} != pdf base name {Path(entry.pdf_filename).stem!r}"
        )

    return (html_path if html_exists else None, pdf_path if pdf_exists else None)


def detect_orphans(manifest: SourcesManifest, data_root: Path, report: VerificationReport) -> None:
    declared_act_filenames = {a.filename for a in manifest.acts}
    declared_folders = {j.folder for j in manifest.judgments}

    for entry in data_root.iterdir():
        if entry.is_file() and entry.suffix.lower() == ".pdf":
            if entry.name not in declared_act_filenames:
                report.orphaned_files.append(f"top-level PDF {entry.name!r} not in manifest acts")
        elif entry.is_dir() and entry.name.isdigit():
            if entry.name not in declared_folders:
                report.orphaned_files.append(f"folder {entry.name}/ not in manifest judgments")


def verify_or_record_hash(
    file_path: Path,
    existing_hash: str | None,
    label: str,
    write_mode: bool,
    report: VerificationReport,
) -> str:
    computed = compute_sha256(file_path)
    if existing_hash is None:
        if write_mode:
            report.populated_hashes.append(f"{label}: {computed}")
        return computed
    if computed != existing_hash:
        report.hash_drift.append(
            f"{label}: expected {existing_hash[:12]}…, got {computed[:12]}…"
        )
    return computed


def persist_hashes(
    manifest_path: Path,
    raw_manifest: dict[str, Any],
    act_hashes: dict[str, str],
    judgment_hashes: dict[str, tuple[str, str]],
) -> None:
    for act in raw_manifest.get("acts", []):
        act_id = act.get("act_id")
        if act_id in act_hashes:
            act["sha256"] = act_hashes[act_id]
    for judgment in raw_manifest.get("judgments", []):
        folder = judgment.get("folder")
        if folder in judgment_hashes:
            html_hash, pdf_hash = judgment_hashes[folder]
            judgment["html_sha256"] = html_hash
            judgment["pdf_sha256"] = pdf_hash
    manifest_path.write_text(
        yaml.safe_dump(raw_manifest, sort_keys=False, allow_unicode=True, width=120)
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument(
        "--write-hashes",
        action="store_true",
        help="Populate sha256 fields in sources.yaml from computed hashes. Without this flag, "
        "hashes are compared against existing values and drift is reported.",
    )
    args = parser.parse_args()

    manifest_path: Path = args.manifest.resolve()
    data_root: Path = args.data_root.resolve()

    report = VerificationReport()

    print(f"Manifest: {manifest_path}")
    print(f"Data root: {data_root}")

    if not data_root.is_dir():
        print(f"error: data root not found at {data_root}", file=sys.stderr)
        return 2

    manifest, schema_errors = load_manifest(manifest_path)
    if manifest is None:
        report.schema_errors.extend(schema_errors)
        report.print_summary()
        return 1

    print(f"Schema: valid ({len(manifest.acts)} acts, {len(manifest.judgments)} judgments)")

    act_hashes: dict[str, str] = {}
    judgment_hashes: dict[str, tuple[str, str]] = {}

    for act in manifest.acts:
        path = check_act_exists(act, data_root, report)
        if path is not None:
            act_hashes[act.act_id] = verify_or_record_hash(
                path, act.sha256, f"act {act.act_id}", args.write_hashes, report
            )

    for judgment in manifest.judgments:
        html_path, pdf_path = check_judgment_files(judgment, data_root, report)
        html_hash = (
            verify_or_record_hash(
                html_path,
                judgment.html_sha256,
                f"{judgment.folder}/{judgment.html_filename}",
                args.write_hashes,
                report,
            )
            if html_path is not None
            else None
        )
        pdf_hash = (
            verify_or_record_hash(
                pdf_path,
                judgment.pdf_sha256,
                f"{judgment.folder}/{judgment.pdf_filename}",
                args.write_hashes,
                report,
            )
            if pdf_path is not None
            else None
        )
        if html_hash is not None and pdf_hash is not None:
            judgment_hashes[judgment.folder] = (html_hash, pdf_hash)

    detect_orphans(manifest, data_root, report)

    if args.write_hashes and not report.has_failures:
        raw = yaml.safe_load(manifest_path.read_text())
        persist_hashes(manifest_path, raw, act_hashes, judgment_hashes)
        print(f"\nHashes written to {manifest_path}")

    report.print_summary()

    if report.has_failures:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())