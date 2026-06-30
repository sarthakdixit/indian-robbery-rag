"""Diagnose the BNS appendix-dedup misfire.

This bypasses the dedup logic in `split_into_sections` and dumps:
  - The first 20 raw section matches (so we can see whether the parser
    detects "1" as section 1 multiple times, or detects "1, 2" then
    something completely different)
  - For each match: number, heading prefix, body length
  - The 200 chars of corpus just BEFORE the section-2 start (so we can
    see what trimming actually delivered to split_into_sections)

Run from repo root:
    python3 scripts/diagnose_bns_parse.py

Pure read-only — no DB writes, no API calls, no chunks.jsonl change.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))

from ingestion.normalize.parse_acts_pdf import (  # noqa: E402
    choose_section_regex,
    clean_page,
    detect_repeating_lines,
    extract_pages,
    skip_table_of_contents,
)


def diagnose(pdf_path: Path, label: str) -> None:
    print(f"\n{'='*70}")
    print(f"  {label}: {pdf_path}")
    print('=' * 70)

    pages_text, _ = extract_pages(pdf_path)
    repeating = detect_repeating_lines(pages_text)
    cleaned_pages = [clean_page(p, repeating) for p in pages_text]
    corpus = "\n\n".join(cleaned_pages)
    print(f"raw corpus chars: {len(corpus):,}")

    trimmed, toc_warning = skip_table_of_contents(corpus)
    print(f"trimmed corpus chars: {len(trimmed):,} "
          f"(removed {len(corpus) - len(trimmed):,} preamble chars)")
    if toc_warning:
        print(f"toc trim warning: {toc_warning}")

    section_re, regex_label = choose_section_regex(trimmed)
    print(f"section regex: {regex_label}")

    # Show the first 600 chars of the trimmed corpus — this is what the
    # body parser starts from. If the SoR is still in there, we'll see it.
    print("\n--- First 600 chars of trimmed corpus ---")
    print(repr(trimmed[:600]))
    print("---")

    # All section matches without any dedup. Show first 25.
    matches = list(section_re.finditer(trimmed))
    print(f"\nTotal section-regex matches: {len(matches)}")
    print("First 25 matches:")
    print(f"  {'idx':>3}  {'num':>5}  {'pos':>7}  heading")
    for i, m in enumerate(matches[:25]):
        print(f"  {i:>3}  {m.group('num'):>5}  {m.start():>7}  "
              f"{m.group('heading')[:60]!r}")

    # Find any duplicates and report their positions
    seen: dict[str, list[int]] = {}
    for i, m in enumerate(matches):
        num = m.group("num")
        seen.setdefault(num, []).append(i)
    dupes = {k: v for k, v in seen.items() if len(v) > 1}
    print(f"\nDuplicate section numbers (across full match list): "
          f"{len(dupes)} numbers")
    for num, positions in list(dupes.items())[:10]:
        print(f"  number {num!r}: matched at indices {positions[:5]}"
              + ("..." if len(positions) > 5 else ""))
        # Show the corpus context around each duplicate position
        for pos_idx in positions[:3]:
            m = matches[pos_idx]
            ctx_start = max(0, m.start() - 80)
            ctx_end = min(len(trimmed), m.start() + 120)
            print(f"    idx={pos_idx} corpus[{m.start()}]: "
                  f"...{trimmed[ctx_start:m.start()]!r}{trimmed[m.start():ctx_end]!r}...")


def main() -> int:
    data_dir = _REPO / "data"
    for pdf_name, label in [
        ("bns_2023.pdf", "BNS"),
        ("ipc_1860.pdf", "IPC"),
        ("bnss_2023.pdf", "BNSS"),
    ]:
        pdf_path = data_dir / pdf_name
        if not pdf_path.is_file():
            print(f"\nSKIP {label}: not found at {pdf_path}")
            continue
        diagnose(pdf_path, label)
    return 0


if __name__ == "__main__":
    sys.exit(main())