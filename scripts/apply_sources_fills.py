"""Apply fills from fills_template.json back into sources.yaml.

The companion to audit_sources_yaml.py and extract_judgment_metadata.py:

  1a. Run audit_sources_yaml.py to generate a manual-fill template.
  1b. OR run extract_judgment_metadata.py to auto-extract from HTML.
  2.  Open fills_template.json in an editor, fill in / correct values.
  3.  Run this script to merge the fills back into sources.yaml.

The template can be in one of two formats:

  - **Flat** (from audit_sources_yaml.py): `{"citation": "2007 SCC", ...}`.
    Every non-blank value is treated as applicable.

  - **Tagged** (from extract_judgment_metadata.py): `{"citation": {"value":
    "2007 SCC", "confidence": "high", "note": "..."}, ...}`. Only fields
    at or above --min-confidence are applied (default: high). Useful when
    you want the auto-extractor to fill in only the things it's certain
    about and leave low-confidence ones for human review.

This script:
  - Validates that every entry has a folder key
  - Only writes fields that have non-empty values in the template
    (so partial fills are OK — re-run audit + apply iteratively)
  - Refuses to overwrite a non-TODO existing value unless --force
    (prevents accidental clobbering of fields you already filled in
    manually)
  - Backs up sources.yaml to sources.yaml.bak before writing

Usage:
  python3 scripts/apply_sources_fills.py
  python3 scripts/apply_sources_fills.py --dry-run             # preview
  python3 scripts/apply_sources_fills.py --force               # overwrite
  python3 scripts/apply_sources_fills.py --min-confidence medium
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("PyYAML is required. Install with: pip install pyyaml", file=sys.stderr)
    sys.exit(2)


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = REPO_ROOT / "sources.yaml"
DEFAULT_TEMPLATE = REPO_ROOT / "fills_template.json"

# Same fields as audit_sources_yaml.py — kept in sync by hand.
# year is also writable because the extractor pulls it out automatically.
APPLIABLE_FIELDS: tuple[str, ...] = (
    "citation",
    "court",
    "indian_kanoon_url",
    "primary_section",
    "year",
)


def is_todo(value: object) -> bool:
    if value is None:
        return True
    s = str(value).strip()
    return s == "" or s.startswith("TODO")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    parser.add_argument("--dry-run", action="store_true",
                        help="Report changes that would be made, don't write.")
    parser.add_argument("--force", action="store_true",
                        help="Overwrite existing non-TODO values too.")
    parser.add_argument("--no-backup", action="store_true",
                        help="Skip creating sources.yaml.bak before writing.")
    parser.add_argument(
        "--min-confidence",
        choices=("high", "medium", "low"),
        default="high",
        help="When the template uses the tagged format "
             "({value, confidence, note}), only apply fields at or above "
             "this confidence level. Default: high.",
    )
    args = parser.parse_args()

    if not args.manifest.is_file():
        print(f"manifest not found at {args.manifest}", file=sys.stderr)
        return 2
    if not args.template.is_file():
        print(f"template not found at {args.template}", file=sys.stderr)
        return 2

    manifest = yaml.safe_load(args.manifest.read_text())
    template = json.loads(args.template.read_text())

    if not isinstance(template, list):
        print("template must be a JSON array", file=sys.stderr)
        return 2

    judgments = manifest.get("judgments", [])
    if not isinstance(judgments, list):
        print("manifest judgments is missing or not a list", file=sys.stderr)
        return 2

    # Index judgments by folder for quick lookup
    by_folder: dict[str, dict] = {}
    for entry in judgments:
        if isinstance(entry, dict):
            folder = entry.get("folder")
            if folder is not None:
                by_folder[str(folder)] = entry

    _CONFIDENCE_RANK = {"low": 0, "medium": 1, "high": 2}
    min_rank = _CONFIDENCE_RANK[args.min_confidence]

    changes_made = 0
    changes_skipped_blank = 0
    changes_skipped_existing = 0
    changes_skipped_low_confidence = 0
    entries_not_found: list[str] = []

    for record in template:
        if not isinstance(record, dict):
            continue
        folder = str(record.get("folder", "")).strip()
        if not folder:
            print("template record missing 'folder'; skipping", file=sys.stderr)
            continue

        entry = by_folder.get(folder)
        if entry is None:
            entries_not_found.append(folder)
            continue

        for field in APPLIABLE_FIELDS:
            raw = record.get(field)

            # Handle two shapes: flat string OR tagged {value, confidence, note}
            if isinstance(raw, dict) and "value" in raw and "confidence" in raw:
                new_value = raw.get("value")
                confidence = raw.get("confidence", "low")
                if _CONFIDENCE_RANK.get(confidence, 0) < min_rank:
                    if new_value is not None and str(new_value).strip() != "":
                        print(f"  folder={folder} field={field}: SKIP "
                              f"(confidence={confidence} below threshold {args.min_confidence})")
                    changes_skipped_low_confidence += 1
                    continue
            else:
                new_value = raw
                confidence = "n/a"  # flat format, no confidence info

            if new_value is None or str(new_value).strip() == "":
                changes_skipped_blank += 1
                continue

            old_value = entry.get(field)
            if not is_todo(old_value) and not args.force:
                if old_value != new_value:
                    print(f"  folder={folder} field={field}: SKIP "
                          f"(already has non-TODO value {old_value!r}; --force to overwrite)")
                    changes_skipped_existing += 1
                continue

            if old_value == new_value:
                # No-op
                continue

            conf_note = f" (confidence={confidence})" if confidence != "n/a" else ""
            print(f"  folder={folder} field={field}{conf_note}: "
                  f"{old_value!r} -> {new_value!r}")
            entry[field] = new_value
            changes_made += 1

    print()
    print("Summary:")
    print(f"  changes to apply:                  {changes_made}")
    print(f"  fields left blank in tmpl:         {changes_skipped_blank}")
    print(f"  fields with existing value:        {changes_skipped_existing}")
    print(f"  fields below confidence threshold: {changes_skipped_low_confidence}")
    if entries_not_found:
        print(f"  template folders not in manifest:  {entries_not_found}")

    if changes_made == 0:
        print("Nothing to write.")
        return 0

    if args.dry_run:
        print("--dry-run: not writing sources.yaml.")
        return 0

    if not args.no_backup:
        backup = args.manifest.with_suffix(".yaml.bak")
        shutil.copy(args.manifest, backup)
        print(f"Backed up to {backup}")

    # Write with reasonable defaults: preserve insertion order, no aliases,
    # plain text scalars where possible
    args.manifest.write_text(
        yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True,
                       default_flow_style=False, width=10000)
    )
    print(f"Wrote {args.manifest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())