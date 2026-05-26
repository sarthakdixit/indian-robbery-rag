"""Audit sources.yaml and report which approved judgment entries still
have TODO placeholders that need filling in.

Outputs both:
  - A human-readable checklist (stdout) for manual editing reference
  - A JSON skeleton (writes to fills_template.json) you can fill in and
    then feed back to apply_sources_fills.py to update sources.yaml.

Usage:
  python3 scripts/audit_sources_yaml.py                # default: writes
                                                        # fills_template.json
  python3 scripts/audit_sources_yaml.py --no-template  # checklist only
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("PyYAML is required. Install with: pip install pyyaml", file=sys.stderr)
    sys.exit(2)


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = REPO_ROOT / "sources.yaml"
DEFAULT_TEMPLATE_OUT = REPO_ROOT / "fills_template.json"


# Fields we expect to fill in. Each maps a manifest field name to a short
# label used in checklist output.
FILLABLE_FIELDS: dict[str, str] = {
    "citation": "Citation (e.g. '(2007) 12 SCC 641')",
    "court": "Court (e.g. 'Supreme Court of India')",
    "indian_kanoon_url": "Indian Kanoon URL",
    "primary_section": "Primary section (e.g. '397 IPC' or '309 BNS')",
}


def is_todo(value: object) -> bool:
    """A field is considered to be a TODO placeholder if it's None, empty,
    or its string repr starts with 'TODO'."""
    if value is None:
        return True
    s = str(value).strip()
    return s == "" or s.startswith("TODO")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--template-out", type=Path, default=DEFAULT_TEMPLATE_OUT)
    parser.add_argument("--no-template", action="store_true",
                        help="Skip writing fills_template.json (checklist only).")
    parser.add_argument("--only-approved", action="store_true", default=True,
                        help="Only audit entries with status=approved (default).")
    parser.add_argument("--all-statuses", dest="only_approved", action="store_false",
                        help="Audit every judgment regardless of status.")
    args = parser.parse_args()

    if not args.manifest.is_file():
        print(f"manifest not found at {args.manifest}", file=sys.stderr)
        return 2

    manifest = yaml.safe_load(args.manifest.read_text())
    if not isinstance(manifest, dict):
        print("manifest is not a YAML mapping", file=sys.stderr)
        return 2

    judgments = manifest.get("judgments", [])
    if not isinstance(judgments, list):
        print("'judgments' key is missing or not a list", file=sys.stderr)
        return 2

    # Collect entries that are (a) approved and (b) have at least one TODO.
    pending: list[dict] = []
    for entry in judgments:
        if not isinstance(entry, dict):
            continue
        status = entry.get("relevance_classifier_status", "")
        if args.only_approved and status != "approved":
            continue
        missing = [f for f in FILLABLE_FIELDS if is_todo(entry.get(f))]
        if missing:
            pending.append({"entry": entry, "missing": missing})

    # Human-readable checklist
    print(f"Audit of {args.manifest}")
    if args.only_approved:
        print(f"Filter: relevance_classifier_status == approved")
    else:
        print(f"Filter: ALL statuses")
    print(f"Found {len(pending)} judgment(s) needing fill-in.")
    print()

    for i, item in enumerate(pending, start=1):
        entry = item["entry"]
        folder = entry.get("folder", "??")
        case_name = entry.get("case_name", "??")
        html = entry.get("html_filename", "")
        print(f"--- [{i}/{len(pending)}] folder={folder} ---")
        print(f"    case_name:  {case_name}")
        if html:
            print(f"    html_file:  {html}")
        print(f"    missing:    {', '.join(item['missing'])}")
        print()

    if args.no_template:
        return 0

    # JSON template the user can fill in
    template = []
    for item in pending:
        entry = item["entry"]
        record = {
            "folder": entry.get("folder", ""),
            "case_name_for_reference_only": entry.get("case_name", ""),
        }
        for field in FILLABLE_FIELDS:
            current = entry.get(field)
            if is_todo(current):
                # Leave blank — user fills in
                record[field] = ""
            else:
                # Already filled in; preserve so apply step is idempotent
                record[field] = current
        template.append(record)

    args.template_out.write_text(json.dumps(template, indent=2, ensure_ascii=False))
    print(f"Wrote fills template to {args.template_out}")
    print(f"Next: edit it with the real values, then run apply_sources_fills.py.")
    return 0


if __name__ == "__main__":
    sys.exit(main())