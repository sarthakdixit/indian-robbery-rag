"""Extract judgment metadata from local Indian Kanoon HTML files.

For each approved judgment in sources.yaml that has TODO placeholders, this
script:

  1. Opens data/<folder>/<html_filename> and parses with BeautifulSoup.
  2. Extracts: court, citation, year, primary_section, indian_kanoon_url.
  3. Tags each extracted field with a confidence level (high / medium / low).
  4. Writes results to fills_template.json with `_confidence` fields.

The extraction is intentionally conservative: when in doubt, mark a field
"low" confidence and leave its value for manual review rather than guess.
"low" confidence fields are NOT auto-applied by apply_sources_fills.py
unless --force is used.

Strategy per field:

  court               High if found in <div class="docsource_main"> or
                       similar Indian Kanoon header element.
                       Medium if pattern-matched in <title> or first <h2>.
                       Low otherwise.

  citation            High if pattern matches "(YYYY) NN SCC NNN" or
                       "AIR YYYY SC NNNN" or similar canonical forms in
                       the document header.
                       Medium if pattern found further down in body.
                       Low otherwise.

  year                High if derivable from citation match or filename
                       suffix (`_on_DD_month_YYYY`).
                       Low otherwise.

  primary_section     High if a single section is overwhelmingly
                       most-mentioned in the body (>=3x runner-up).
                       Medium if a leader exists but margin is small.
                       Low if no clear leader or no sections found.

  indian_kanoon_url   High if <meta property="og:url"> or <link
                       rel="canonical"> is present and points to
                       indiankanoon.org.
                       Medium if a doc_id pattern appears in any URL-like
                       string in the document (any href, comment, etc.).
                       Low otherwise.

Usage:
  python3 scripts/extract_judgment_metadata.py
  python3 scripts/extract_judgment_metadata.py --folder 12   # just one
  python3 scripts/extract_judgment_metadata.py --verbose
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

try:
    import yaml
except ImportError:
    print("PyYAML is required. Install with: pip install pyyaml", file=sys.stderr)
    sys.exit(2)

try:
    from bs4 import BeautifulSoup
except ImportError:
    print("beautifulsoup4 is required. Install with: pip install beautifulsoup4 lxml",
          file=sys.stderr)
    sys.exit(2)


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = REPO_ROOT / "sources.yaml"
DEFAULT_DATA_ROOT = REPO_ROOT / "data"
DEFAULT_TEMPLATE_OUT = REPO_ROOT / "fills_template.json"


# --- Regex toolbox ---------------------------------------------------------
# Standard SCC / AIR / criminal-appeal citation forms. Conservative — we
# only match patterns that would actually appear in a real citation, not
# every numeric expression.
_CITATION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\(\s*(\d{4})\s*\)\s*\d+\s*SCC\s*\d+", re.IGNORECASE),
    re.compile(r"AIR\s+(\d{4})\s+SC\s+\d+", re.IGNORECASE),
    re.compile(r"\(\s*(\d{4})\s*\)\s*\d+\s*SCC\s*\(Cri\)\s*\d+", re.IGNORECASE),
    re.compile(r"(\d{4})\s*Cri\.?\s*LJ\s*\d+", re.IGNORECASE),
    re.compile(r"MANU/[A-Z]{2}/\d+/(\d{4})", re.IGNORECASE),
)

# Section references in the body. Recognise:
#   "section 397"        "section 397 IPC"       "section 397 of the IPC"
#   "Section 397 of the Indian Penal Code"
#   "s. 397"             "s.397"
#   "§397"
#   "397 IPC"            "397 BNS"
# After extracting digits, we filter to in-scope ranges: IPC 378-402, BNS 303-313.
_SECTION_RE: re.Pattern[str] = re.compile(
    r"""(?ix)
    (?:section|sec\.?|s\.|§)\s*(\d{1,4})            # "section 397", "s. 397", "§397"
    |
    \b(\d{1,4})\s*(?:IPC|BNS|of\s+the\s+(?:Indian\s+Penal\s+Code|Bharatiya\s+Nyaya\s+Sanhita))
    """
)

# In-scope robbery-adjacent sections (approximate; the chunker generates a
# wider net but for "primary_section" we mark anything near robbery as plausible).
_INSCOPE_IPC = set(range(378, 403))  # theft (378) through dacoity-related (402)
_INSCOPE_BNS = set(range(303, 314))  # theft+robbery+dacoity provisions

# URL extraction.
_IK_DOC_ID_RE: re.Pattern[str] = re.compile(
    r"indiankanoon\.org/doc/(\d+)/?", re.IGNORECASE
)
_IK_DOC_PATH_RE: re.Pattern[str] = re.compile(
    r"/doc/(\d+)/?", re.IGNORECASE
)

# Browser-injected "saved from url=(NNNN)URL" comment. NNNN is the URL
# length in characters that Chrome/Firefox/Edge add to "Save Page As".
# The URL ends at whitespace or `-->`. Captures the URL only.
_SAVED_FROM_RE: re.Pattern[str] = re.compile(
    r"saved from url=\(\d+\)([^\s>]+)", re.IGNORECASE
)

# Filename date suffix: "..._on_29_november_2023.html"
_FILENAME_DATE_RE: re.Pattern[str] = re.compile(
    r"_on_(?:\d+_)?[a-z]+_(\d{4})\.html?$", re.IGNORECASE
)


# --- Data structure --------------------------------------------------------
@dataclass
class ExtractedField:
    """A single extracted value plus its confidence."""
    value: str | int | None
    confidence: str  # "high" | "medium" | "low"
    note: str = ""

    def as_dict(self) -> dict:
        return {"value": self.value, "confidence": self.confidence, "note": self.note}


# --- Field extractors ------------------------------------------------------
def extract_court(soup: BeautifulSoup, title_text: str) -> ExtractedField:
    """Indian Kanoon's saved pages put the court name in an element with
    class="docsource_main". The wrapping tag varies (h3 most commonly,
    sometimes h2 or div), so we search by class regardless of tag.
    """
    # Try the canonical Indian Kanoon source element (any tag)
    el = soup.find(class_="docsource_main")
    if el and el.get_text(strip=True):
        return ExtractedField(value=el.get_text(strip=True), confidence="high",
                              note=f"docsource_main (<{el.name}>)")

    # Fallback: look for an h2/h3 near the doc title that contains a
    # recognised court keyword. Only checked if docsource_main is absent.
    for tag in soup.find_all(["h2", "h3"]):
        txt = tag.get_text(strip=True)
        if any(k in txt.lower() for k in (
            "supreme court", "high court", "district court", "sessions",
            "magistrate", "tribunal",
        )):
            return ExtractedField(value=txt, confidence="medium",
                                  note=f"{tag.name} text match")

    # Try the page title — sometimes carries court hints
    for keyword in ("Supreme Court", "High Court"):
        if keyword in title_text:
            return ExtractedField(value=keyword + " (inferred from title)",
                                  confidence="low",
                                  note=f"title keyword: {keyword}")

    return ExtractedField(value=None, confidence="low", note="no court element found")


def extract_citation_and_year(soup: BeautifulSoup, filename: str) -> tuple[ExtractedField, ExtractedField]:
    """Look for citation patterns in the document. Returns (citation, year)."""
    # The Indian Kanoon main content is wrapped in <div class="judgments">.
    # Without this scoping we pick up nav/search/footer text in the first
    # 3000 chars (search bar contains "court", footer has nav links etc.)
    # and miss real citations entirely.
    judgments_div = soup.find("div", class_="judgments")
    if judgments_div is not None:
        body_text = judgments_div.get_text("\n", strip=True)
    else:
        # Fallback: whole-page text. Older or unusual Indian Kanoon saves
        # may not have this wrapper.
        body_text = soup.get_text("\n", strip=True)

    head_text = body_text[:3000]

    for pattern in _CITATION_PATTERNS:
        m = pattern.search(head_text)
        if m:
            cit = m.group(0).strip()
            year = int(m.group(1))
            return (
                ExtractedField(value=cit, confidence="high", note="header regex match"),
                ExtractedField(value=year, confidence="high", note="from citation"),
            )

    # Try the rest of the body
    for pattern in _CITATION_PATTERNS:
        m = pattern.search(body_text)
        if m:
            cit = m.group(0).strip()
            year = int(m.group(1))
            return (
                ExtractedField(value=cit, confidence="medium",
                               note="body regex match (not in header)"),
                ExtractedField(value=year, confidence="medium", note="from body citation"),
            )

    # Last resort: year from filename suffix
    fn_match = _FILENAME_DATE_RE.search(filename)
    year_value: ExtractedField
    if fn_match:
        year_value = ExtractedField(value=int(fn_match.group(1)),
                                    confidence="medium",
                                    note=f"filename date suffix")
    else:
        year_value = ExtractedField(value=None, confidence="low",
                                    note="no year found")

    return (
        ExtractedField(value=None, confidence="low",
                       note="no recognized citation pattern found"),
        year_value,
    )


def extract_primary_section(soup: BeautifulSoup) -> ExtractedField:
    """Count section references in the body, pick the most-mentioned that
    falls in robbery-related ranges (IPC 378-402, BNS 303-313)."""
    # Scope to the case body to avoid false positives from page chrome
    # (search bar placeholders, footer text, etc.).
    judgments_div = soup.find("div", class_="judgments")
    container = judgments_div if judgments_div is not None else soup
    text = container.get_text(" ", strip=True)

    counts: Counter[int] = Counter()
    for match in _SECTION_RE.finditer(text):
        # The regex has two alternatives; one of the two groups will be
        # populated per match.
        num_str = match.group(1) or match.group(2)
        if num_str is None:
            continue
        try:
            num = int(num_str)
        except ValueError:
            continue
        if num in _INSCOPE_IPC or num in _INSCOPE_BNS:
            counts[num] += 1

    if not counts:
        return ExtractedField(value=None, confidence="low",
                              note="no in-scope section references found")

    # Pick most-mentioned
    sorted_counts = counts.most_common()
    top_num, top_count = sorted_counts[0]

    # Decide IPC vs BNS by which range it falls in. The corpus is mostly
    # pre-BNS (2024 onward) cases referring to IPC; cases citing BNS sections
    # are rare so far.
    if top_num in _INSCOPE_BNS:
        primary = f"{top_num} BNS"
    else:
        primary = f"{top_num} IPC"

    # Confidence: high if leader has 3x or more references than runner-up,
    # OR if there's no runner-up.
    if len(sorted_counts) == 1:
        confidence = "high"
        note = f"only section found ({top_count} mentions)"
    else:
        runner_up_count = sorted_counts[1][1]
        ratio = top_count / runner_up_count if runner_up_count > 0 else float("inf")
        if ratio >= 3.0:
            confidence = "high"
            note = f"{top_count} mentions vs runner-up {runner_up_count}"
        else:
            confidence = "medium"
            note = (f"{top_count} mentions vs runner-up {sorted_counts[1][0]} "
                    f"with {runner_up_count} mentions")

    return ExtractedField(value=primary, confidence=confidence, note=note)


def extract_indian_kanoon_url(soup: BeautifulSoup, existing_doc_id: str | None,
                              raw_html: str) -> ExtractedField:
    """Find or reconstruct the Indian Kanoon URL.

    Strategies, in confidence order:
      1. existing indian_kanoon_doc_id field in sources.yaml
      2. <meta property="og:url"> tag
      3. <link rel="canonical"> tag
      4. browser-recorded "saved from url=(NNNN)..." comment
         — this is high confidence because it's the exact URL the file
         was downloaded from, recorded by the browser at save time
      5. any other indiankanoon.org/doc/<id>/ URL in the document
         — medium confidence: could be a cross-reference to a different
         case mentioned in the body
    """
    # 1. If sources.yaml already has indian_kanoon_doc_id, use it
    if existing_doc_id:
        return ExtractedField(
            value=f"https://indiankanoon.org/doc/{existing_doc_id}/",
            confidence="high",
            note="constructed from sources.yaml indian_kanoon_doc_id",
        )

    # 2. <meta property="og:url">
    og = soup.find("meta", attrs={"property": "og:url"})
    if og and og.get("content") and "indiankanoon.org" in og.get("content", ""):
        return ExtractedField(value=og["content"], confidence="high",
                              note="og:url meta tag")

    # 3. <link rel="canonical">
    canonical = soup.find("link", attrs={"rel": "canonical"})
    if canonical and canonical.get("href") and "indiankanoon.org" in canonical.get("href", ""):
        return ExtractedField(value=canonical["href"], confidence="high",
                              note="canonical link")

    # 4. Browser-recorded "saved from url=(NNNN)..." comment.
    # We search the raw HTML directly (not str(soup)) because some parser
    # configurations strip pre-<html> comments. The comment is typically
    # on the second line of the file. Pattern: "saved from url=(NNNN)URL"
    # where NNNN is the URL length in characters.
    saved_from_match = _SAVED_FROM_RE.search(raw_html)
    if saved_from_match:
        url = saved_from_match.group(1)
        # Sanity-check that the captured URL is from indiankanoon
        doc_match = _IK_DOC_ID_RE.search(url)
        if doc_match:
            doc_id = doc_match.group(1)
            return ExtractedField(
                value=f"https://indiankanoon.org/doc/{doc_id}/",
                confidence="high",
                note=f"browser saved-from comment (doc_id {doc_id})",
            )

    # 5. Any indiankanoon.org/doc/<id>/ URL elsewhere in the document.
    # Medium confidence: this could be a cross-reference to a different
    # judgment mentioned in the body text, not the case itself.
    full_text = str(soup)
    m = _IK_DOC_ID_RE.search(full_text)
    if m:
        doc_id = m.group(1)
        return ExtractedField(value=f"https://indiankanoon.org/doc/{doc_id}/",
                              confidence="medium",
                              note=f"doc_id {doc_id} found in document text "
                                   f"(might be a cross-reference)")

    return ExtractedField(value=None, confidence="low",
                          note="no indiankanoon URL or doc_id found in HTML")


# --- Main extraction loop --------------------------------------------------
def extract_for_entry(entry: dict, data_root: Path, verbose: bool) -> dict:
    """Extract metadata for a single judgment entry from sources.yaml."""
    folder = str(entry.get("folder", ""))
    html_filename = entry.get("html_filename", "")
    html_path = data_root / folder / html_filename

    out = {
        "folder": folder,
        "case_name_for_reference_only": entry.get("case_name", ""),
        "html_path": str(html_path.relative_to(data_root.parent)) if html_path.exists() else None,
    }

    if not html_path.is_file():
        out["error"] = f"HTML file not found at {html_path}"
        return out

    with html_path.open(encoding="utf-8", errors="replace") as f:
        html = f.read()

    soup = BeautifulSoup(html, "lxml")
    title_text = soup.title.get_text(strip=True) if soup.title else ""

    if verbose:
        print(f"  [{folder}] parsing {html_filename}")

    court = extract_court(soup, title_text)
    citation, year = extract_citation_and_year(soup, html_filename)
    primary_section = extract_primary_section(soup)
    existing_doc_id = entry.get("indian_kanoon_doc_id")
    ik_url = extract_indian_kanoon_url(soup, existing_doc_id, raw_html=html)

    out["court"] = court.as_dict()
    out["citation"] = citation.as_dict()
    out["year"] = year.as_dict()
    out["primary_section"] = primary_section.as_dict()
    out["indian_kanoon_url"] = ik_url.as_dict()

    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--template-out", type=Path, default=DEFAULT_TEMPLATE_OUT)
    parser.add_argument("--folder", type=str, default=None,
                        help="Process only this folder number (debug).")
    parser.add_argument("--all-statuses", action="store_true",
                        help="Process every judgment, not just approved ones.")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    if not args.manifest.is_file():
        print(f"manifest not found at {args.manifest}", file=sys.stderr)
        return 2

    manifest = yaml.safe_load(args.manifest.read_text())
    judgments = manifest.get("judgments", [])

    # Filter to candidates
    candidates = []
    for entry in judgments:
        if not isinstance(entry, dict):
            continue
        if args.folder is not None and str(entry.get("folder", "")) != args.folder:
            continue
        if not args.all_statuses and entry.get("relevance_classifier_status") != "approved":
            continue
        candidates.append(entry)

    if not candidates:
        print("no candidate entries found", file=sys.stderr)
        return 1

    print(f"Extracting metadata from {len(candidates)} judgment(s)...")

    results = []
    for entry in candidates:
        result = extract_for_entry(entry, args.data_root, args.verbose)
        results.append(result)

    # Summary stats
    high_count: Counter[str] = Counter()
    medium_count: Counter[str] = Counter()
    low_count: Counter[str] = Counter()
    errors = 0
    for r in results:
        if "error" in r:
            errors += 1
            continue
        for field in ("court", "citation", "year", "primary_section", "indian_kanoon_url"):
            fd = r.get(field, {})
            conf = fd.get("confidence") if isinstance(fd, dict) else None
            if conf == "high":
                high_count[field] += 1
            elif conf == "medium":
                medium_count[field] += 1
            elif conf == "low":
                low_count[field] += 1

    print()
    print(f"Confidence summary (out of {len(candidates) - errors} successfully parsed):")
    print(f"  {'field':<20} {'high':>6} {'medium':>8} {'low':>6}")
    for field in ("court", "citation", "year", "primary_section", "indian_kanoon_url"):
        print(f"  {field:<20} {high_count[field]:>6} {medium_count[field]:>8} {low_count[field]:>6}")
    if errors:
        print(f"  {errors} entry(ies) had errors (HTML not found etc.)")

    args.template_out.write_text(json.dumps(results, indent=2, ensure_ascii=False))
    print()
    print(f"Wrote results to {args.template_out}")
    print(f"Review medium/low confidence fields, then run apply_sources_fills.py "
          f"(with adapted format — see next step).")
    return 0


if __name__ == "__main__":
    sys.exit(main())