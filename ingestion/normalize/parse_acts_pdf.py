"""Parse an Indian bare-act PDF into structured ActSection records.

Targets the indiacode.nic.in PDF layout for BNS 2023, IPC 1860, and
BNSS 2023. The parser is heuristic: section boundaries are detected by
regex, chapter headings collected as context, and anything ambiguous
surfaces as a parse_warning on the NormalizedAct.

Strategy:
  1. Extract text page-by-page with pdfplumber.
  2. Strip repeating page headers/footers (page numbers, banner lines).
  3. Concatenate into one corpus, then split by SECTION_START regex.
  4. For each detected section, capture its number, heading, and body.
  5. Track the most recent CHAPTER heading and attach to following sections.

The parser is NOT a full bare-act normalizer. It is good enough to:
  - Identify the robbery-relevant sections (303-313 in BNS, 378-402 in IPC)
  - Produce reasonable text chunks for embedding
  - Surface warnings when its heuristics fail so a human can fix manually
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import pdfplumber  # type: ignore[import-untyped]


SECTION_START_RE: re.Pattern[str] = re.compile(
    r"(?m)^\s*(?P<num>\d{1,3}[A-Z]{0,2})\.\s+(?P<heading>[^\n]{0,200})$"
)

SECTION_START_RE_VERBOSE: re.Pattern[str] = re.compile(
    r"(?m)^\s*Section\s+(?P<num>\d{1,3}[A-Z]{0,2})\.\s+(?P<heading>[^\n]{0,200})$"
)

CHAPTER_START_RE: re.Pattern[str] = re.compile(
    r"(?m)^\s*CHAPTER\s+(?P<chapnum>[IVXLCDM]+|\d+)\s*$"
)

TOC_MARKER_RE: re.Pattern[str] = re.compile(
    r"(?i)ARRANGEMENT\s+OF\s+(SECTIONS|CLAUSES)"
)

PAGE_NUMBER_RE: re.Pattern[str] = re.compile(r"^\s*\d+\s*$")
WHITESPACE_RE: re.Pattern[str] = re.compile(r"[ \t]+")
MULTIBLANK_RE: re.Pattern[str] = re.compile(r"\n{3,}")

MIN_SECTION_BODY_CHARS: int = 20
MAX_HEADING_LEN: int = 200

logger = logging.getLogger(__name__)


@dataclass
class RawSection:
    number: str
    heading: str
    text: str
    chapter: str | None = None
    chapter_number: str | None = None


@dataclass
class ParseActResult:
    sections: list[RawSection] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def detect_repeating_lines(pages_text: list[str], min_repeats: int = 3) -> set[str]:
    line_counts: dict[str, int] = {}
    for page in pages_text:
        seen_on_this_page: set[str] = set()
        for line in page.splitlines():
            stripped = line.strip()
            if not stripped or PAGE_NUMBER_RE.match(stripped):
                continue
            if stripped in seen_on_this_page:
                continue
            seen_on_this_page.add(stripped)
            line_counts[stripped] = line_counts.get(stripped, 0) + 1

    return {line for line, count in line_counts.items() if count >= min_repeats}


def clean_page(page_text: str, repeating_lines: set[str]) -> str:
    cleaned_lines: list[str] = []
    for line in page_text.splitlines():
        stripped = line.strip()
        if not stripped:
            cleaned_lines.append("")
            continue
        if PAGE_NUMBER_RE.match(stripped):
            continue
        if stripped in repeating_lines:
            continue
        cleaned_lines.append(WHITESPACE_RE.sub(" ", line).rstrip())
    return "\n".join(cleaned_lines)


def extract_pages(pdf_path: Path) -> tuple[list[str], list[str]]:
    pages_text: list[str] = []
    warnings: list[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page_index, page in enumerate(pdf.pages):
            try:
                text = page.extract_text() or ""
            except Exception as e:
                warnings.append(f"page {page_index + 1}: extract_text raised {type(e).__name__}: {e}")
                text = ""
            if not text.strip():
                warnings.append(f"page {page_index + 1}: empty text (possibly scanned image)")
            pages_text.append(text)
    return pages_text, warnings


def skip_table_of_contents(corpus: str) -> tuple[str, str | None]:
    """If the corpus starts with an 'ARRANGEMENT OF SECTIONS' table-of-contents,
    return the corpus with the TOC removed. Otherwise return the corpus unchanged.

    Strategy: bare-act PDFs from indiacode.nic.in put the TOC right after an
    'ARRANGEMENT OF SECTIONS' marker, mirroring the body's chapter/section
    structure with one-line entries. The body proper starts at the LAST
    'CHAPTER I' (or 'CHAPTER 1') in the document — by that point we've passed
    the entire TOC, which had its own CHAPTER I, CHAPTER II, etc.

    If 'ARRANGEMENT OF SECTIONS' is not present, the PDF likely uses a flat
    structure (e.g., third-party IPC dumps), and we return the corpus unchanged.

    Returns (trimmed_corpus, warning_message_or_None).
    """
    toc_match = TOC_MARKER_RE.search(corpus)
    if toc_match is None:
        return corpus, None

    chapter_i_matches = [
        m for m in CHAPTER_START_RE.finditer(corpus, pos=toc_match.end())
        if m.group("chapnum") in ("I", "1")
    ]
    if len(chapter_i_matches) >= 2:
        body_start = chapter_i_matches[-1].start()
        return corpus[body_start:], None
    if len(chapter_i_matches) == 1:
        return corpus, (
            "found ARRANGEMENT OF SECTIONS marker but only one CHAPTER I header "
            "after it; cannot distinguish TOC from body — some sections may be "
            "misparsed as TOC entries"
        )
    return corpus, (
        "found ARRANGEMENT OF SECTIONS marker but no CHAPTER I headers after it; "
        "skipping TOC removal — some sections may be misparsed as TOC entries"
    )


def choose_section_regex(corpus: str) -> tuple[re.Pattern[str], str]:
    """Pick the section-start regex that matches more headings in this corpus.

    indiacode.nic.in PDFs and modern BNS/BNSS PDFs use `309. Heading`. Some
    third-party IPC PDFs use `Section 309. Heading`. Try both, pick the more
    productive one.
    """
    standard_count = len(SECTION_START_RE.findall(corpus))
    verbose_count = len(SECTION_START_RE_VERBOSE.findall(corpus))
    if verbose_count > standard_count:
        return SECTION_START_RE_VERBOSE, "verbose ('Section N. heading')"
    return SECTION_START_RE, "standard ('N. heading')"


def split_into_sections(
    corpus: str, section_re: re.Pattern[str]
) -> tuple[list[RawSection], list[str]]:
    sections: list[RawSection] = []
    warnings: list[str] = []
    current_chapter: str | None = None
    current_chapter_number: str | None = None

    matches = list(section_re.finditer(corpus))
    if not matches:
        warnings.append("no section markers matched the regex; PDF layout may be unrecognized")
        return sections, warnings

    chapter_positions = [(m.start(), m.group("chapnum")) for m in CHAPTER_START_RE.finditer(corpus)]

    last_section_number: int | None = None

    for index, match in enumerate(matches):
        section_start = match.start()
        section_end = matches[index + 1].start() if index + 1 < len(matches) else len(corpus)

        for chapter_pos, chapter_num in chapter_positions:
            if chapter_pos < section_start:
                if current_chapter_number != chapter_num:
                    current_chapter_number = chapter_num
                    chapter_heading_match = re.search(
                        rf"CHAPTER\s+{re.escape(chapter_num)}\s*\n+([^\n]+)",
                        corpus[chapter_pos:],
                    )
                    current_chapter = (
                        chapter_heading_match.group(1).strip()
                        if chapter_heading_match
                        else None
                    )

        number = match.group("num").strip()
        heading = match.group("heading").strip().rstrip(".")
        body_start = match.end()
        body = corpus[body_start:section_end].strip()
        body = MULTIBLANK_RE.sub("\n\n", body)

        if heading.startswith("(") and ")" in heading[:5]:
            body = heading + "\n" + body
            heading = ""

        if len(body) < MIN_SECTION_BODY_CHARS:
            warnings.append(f"section {number}: body too short ({len(body)} chars); may be misparsed")
            continue

        if number.isdigit():
            current_int = int(number)
            if last_section_number is not None and current_int - last_section_number > 5:
                warnings.append(
                    f"section number jump from {last_section_number} to {current_int}; "
                    f"intermediate sections may be missing"
                )
            last_section_number = current_int

        if len(heading) > MAX_HEADING_LEN:
            warnings.append(f"section {number}: heading too long, truncating")
            heading = heading[:MAX_HEADING_LEN]

        sections.append(
            RawSection(
                number=number,
                heading=heading,
                text=body,
                chapter=current_chapter,
                chapter_number=current_chapter_number,
            )
        )

    # Post-parse cleanup: bare-act PDFs contain three classes of false
    # positives that match the section-heading regex:
    #
    #   (a) FOOTNOTES inside the body — e.g. a footnote "1. 1st day of
    #       July, 2024, ..." appears below section 1, and the regex
    #       grabs the "1. 1st" prefix as if it were section 1 again.
    #   (b) THE APPENDIX at the very end — Statement of Objects and
    #       Reasons, with items numbered 1., 2., 3., ... matching the
    #       regex.
    #   (c) PARSE ARTIFACTS — the same section heading detected twice
    #       in adjacent positions because of PDF text-flow quirks.
    #
    # All three share one property: the spurious match has a section
    # number that is NOT strictly greater than the highest legitimate
    # number we've already seen. Real bare-act sections increase
    # monotonically; junk does not. So we drop any match whose purely-
    # numeric number is <= the running max.
    #
    # Letter-suffixed sections (e.g. 376A, 376B) are kept unconditionally
    # — they don't update the running max (since `int("376A")` would
    # fail) and shouldn't be dropped just because their numeric parent
    # came first. This matches the existing logic at line 220-227.
    running_max: int | None = None
    kept_sections: list[RawSection] = []
    skipped_numbers: list[str] = []
    for sec in sections:
        if sec.number.isdigit():
            n = int(sec.number)
            if running_max is not None and n <= running_max:
                skipped_numbers.append(sec.number)
                continue
            running_max = n
        kept_sections.append(sec)

    if skipped_numbers:
        warnings.append(
            f"dropped {len(skipped_numbers)} non-monotonic section matches "
            f"(footnotes/appendix/parse-artifacts); examples: "
            f"{skipped_numbers[:8]}"
        )

    return kept_sections, warnings


def parse_act_pdf(pdf_path: Path) -> ParseActResult:
    result = ParseActResult()

    if not pdf_path.is_file():
        result.warnings.append(f"PDF not found at {pdf_path}")
        return result

    pages_text, page_warnings = extract_pages(pdf_path)
    result.warnings.extend(page_warnings)

    if not any(p.strip() for p in pages_text):
        result.warnings.append("PDF appears to contain no extractable text (possibly fully scanned)")
        return result

    repeating = detect_repeating_lines(pages_text)
    cleaned_pages = [clean_page(p, repeating) for p in pages_text]
    corpus = "\n\n".join(cleaned_pages)

    trimmed, toc_warning = skip_table_of_contents(corpus)
    if toc_warning:
        result.warnings.append(toc_warning)
    if len(trimmed) < len(corpus):
        result.warnings.append(
            f"trimmed {len(corpus) - len(trimmed):,} chars of table-of-contents preamble"
        )

    section_re, regex_label = choose_section_regex(trimmed)
    result.warnings.append(f"using {regex_label} section-heading regex")

    sections, split_warnings = split_into_sections(trimmed, section_re)
    result.sections = sections
    result.warnings.extend(split_warnings)

    return result