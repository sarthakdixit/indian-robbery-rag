"""Citation extraction and verification.

The LLM is instructed to cite retrieved chunks by 1-indexed number,
producing answer text with inline markers like `[1]`, `[2]`. This module:

  1. Extracts those markers from raw LLM output.
  2. Validates each marker against the set of retrieved chunks that were
     given to the LLM.
  3. Strips markers that don't correspond to any retrieved chunk
     (defends against hallucinated citation numbers).

Two things deliberately NOT done here:

  - **Semantic alignment.** We don't try to verify that the chunk cited
    in a sentence is *semantically* the right one for that sentence.
    That requires LLM-as-judge or careful NLI, well outside Batch 3
    scope. design.md FR-8 calls only for existence verification.

  - **Renumbering after stripping.** If we strip `[3]` because it was
    hallucinated, we don't compact `[1] [2] [4]` to `[1] [2] [3]`.
    Renumbering would require also rewriting the citation cards on the
    frontend, and creates an opportunity for off-by-one errors. Simpler
    to leave a gap and let the frontend skip missing citation numbers.

Pure functions, no I/O, no async — fully unit-testable.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from backend.app.protocols.retrieval import RetrievedChunk


logger = logging.getLogger(__name__)


# Match citation markers: an open bracket, a positive integer, a close
# bracket. We accept the simpler `[1]` form rather than fancier forms like
# `[1, 2]` because we ask the LLM to use only the simple form, and parsing
# combinations introduces ambiguity (is `[10]` ten, or one-and-zero?).
_CITATION_RE = re.compile(r"\[(\d+)\]")


@dataclass(frozen=True)
class VerifiedAnswer:
    """An LLM answer with its citations validated and surfaced separately.

    `answer_text` is the original LLM output with bad citation markers
    (those referring to a number outside 1..len(chunks)) stripped.

    `used_chunks` is the subset of retrieved chunks that the LLM actually
    cited at least once, in citation-number order (chunk for `[1]` first,
    chunk for `[2]` second, etc.), with hallucinated numbers excluded.
    The frontend renders these as numbered citation cards.

    `stripped_citation_numbers` records which citation numbers were
    removed — useful for the admin dashboard so we can spot LLM
    behavior issues over time.

    `prompt_tokens` and `output_tokens` are pass-through from the
    Gemini SDK's `usage_metadata` and are used by Chunk 4.4's
    QueryLogWriter for cost accounting. Either may be None if the
    SDK didn't surface usage info on this particular response.
    """

    answer_text: str
    used_chunks: list[RetrievedChunk]
    stripped_citation_numbers: list[int]
    prompt_tokens: int | None = None
    output_tokens: int | None = None


def extract_citation_numbers(text: str) -> list[int]:
    """Return citation numbers in the order they appear in the text.

    Duplicates are preserved — `"foo [1] bar [1] baz [2]"` returns
    `[1, 1, 2]`. The verification step deduplicates when building the
    `used_chunks` list.
    """
    return [int(m.group(1)) for m in _CITATION_RE.finditer(text)]


def verify_and_strip(
    answer_text: str,
    chunks_provided_to_llm: list[RetrievedChunk],
) -> VerifiedAnswer:
    """Validate citations against the chunks given to the LLM.

    Behaviour:
      - Citation numbers in range `[1, len(chunks)]` are kept.
      - Numbers outside that range are removed from the answer text
        (so `[7]` becomes `` if only 5 chunks were provided).
      - The returned `used_chunks` is the deduplicated set of chunks
        actually cited at least once, in first-cited order.

    Edge case: if the LLM produces an answer with zero citations, we
    return the answer unchanged with an empty `used_chunks` list. The
    pipeline layer decides whether to surface that as a soft warning
    (uncited answer is suspicious) or accept it (the LLM may have
    declined to answer with "the sources do not address this").
    """
    n_chunks = len(chunks_provided_to_llm)

    cited_numbers = extract_citation_numbers(answer_text)

    # Partition: which are valid, which are hallucinated.
    valid_numbers_set: set[int] = set()
    stripped_numbers_set: set[int] = set()
    for num in cited_numbers:
        if 1 <= num <= n_chunks:
            valid_numbers_set.add(num)
        else:
            stripped_numbers_set.add(num)

    if stripped_numbers_set:
        logger.info(
            "citation verification: stripped %d hallucinated citation(s) %s "
            "(LLM was given %d chunks)",
            len(stripped_numbers_set), sorted(stripped_numbers_set), n_chunks,
        )

    # Strip the bad ones from the text. We only strip the marker, not the
    # surrounding text — the sentence may still be substantive even if its
    # citation was wrong.
    cleaned_text = answer_text
    if stripped_numbers_set:
        def _replace(match: re.Match[str]) -> str:
            num = int(match.group(1))
            if num in stripped_numbers_set:
                return ""
            return match.group(0)
        cleaned_text = _CITATION_RE.sub(_replace, cleaned_text)
        # Tidy up double spaces left behind by removed markers.
        cleaned_text = re.sub(r" {2,}", " ", cleaned_text)
        # And any space-before-punctuation introduced by the same.
        cleaned_text = re.sub(r" ([.,;:!?])", r"\1", cleaned_text)

    # Build used_chunks in first-cited order.
    used_chunks: list[RetrievedChunk] = []
    seen: set[int] = set()
    for num in cited_numbers:
        if num in valid_numbers_set and num not in seen:
            seen.add(num)
            used_chunks.append(chunks_provided_to_llm[num - 1])

    return VerifiedAnswer(
        answer_text=cleaned_text,
        used_chunks=used_chunks,
        stripped_citation_numbers=sorted(stripped_numbers_set),
    )