"""Generator: build a context-augmented prompt, call the LLM, verify cites.

The `Generator` class takes a `GenerationClient` (protocol) plus a query
and the retrieved chunks, and returns a `VerifiedAnswer`. It owns:

  - The system prompt (versioned here as a module constant; bumping it
    invalidates any cached generations that don't carry a matching
    prompt version, in case we add prompt versioning later).
  - The format used to lay out retrieved chunks as numbered context in
    the user message.
  - Citation post-processing — calling out to `citations.verify_and_strip`.

What lives outside this module:

  - Retrieval (Chunk 3.2) — produces the chunks this module formats.
  - Caching (Chunk 3.4) — wraps Generator calls for repeat-query elision.
  - HTTP error mapping (Batch 4) — translates raised exceptions into
    user-facing HTTP responses.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from backend.app.protocols.retrieval import RetrievedChunk
from backend.app.rag.citations import VerifiedAnswer, verify_and_strip

if TYPE_CHECKING:
    from backend.app.protocols.generation import GenerationClient


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Prompts.
# ---------------------------------------------------------------------------
# The system prompt is the most consequential constant in this codebase.
# Every word here gets multiplied by every answered query. Changes should
# be reviewed deliberately and re-evaluated against the Batch 8 eval set
# before being merged.
#
# Design notes for the current version (v1):
#
#   - "Answer ONLY from the provided sources" is the central constraint.
#     Without it, gemini-2.5-flash-lite will happily synthesize legal
#     content from its training data, which defeats the purpose of RAG
#     for legal Q&A.
#
#   - The BNS-in-force date (1 July 2024) is stated explicitly because
#     the corpus has both IPC and BNS sections and the LLM otherwise
#     has no anchor for which applies to what date range.
#
#   - Citations are mandated by example, not just by instruction. LLMs
#     follow example formats more reliably than rule statements.
#
#   - The "If sources do not contain the answer" escape hatch is critical:
#     it gives the LLM a safe action when the retrieval was off-target,
#     instead of forcing it to confabulate.
SYSTEM_PROMPT: str = """You are a legal research assistant specialized in Indian criminal law, \
specifically robbery offences under the Bharatiya Nyaya Sanhita, 2023 (BNS) \
and the Indian Penal Code, 1860 (IPC).

The BNS came into force on 1 July 2024. Offences committed before that date \
are governed by the IPC; offences after, by the BNS. Several provisions map \
across the two codes (e.g., IPC §§ 390-402 broadly correspond to BNS §§ 309-313).

RULES:

1. Answer ONLY using the numbered sources provided in the user message. \
Do not draw on outside knowledge of Indian law.

2. Cite every factual claim using the marker [N], where N is the number of \
the source. Example: "Robbery is a special form of theft involving force [1], \
and aggravated robbery with a deadly weapon attracts enhanced punishment [3]."

3. If the provided sources do not contain enough information to answer the \
question, say so explicitly. Do NOT invent or extrapolate.

4. Keep answers concise (3-6 sentences typically). Prefer plain English over \
legalese where both are accurate.

5. When IPC and BNS provisions are both relevant, name both with their \
respective citations. Do not treat them as identical even when they correspond.

6. Add a disclaimer reminding the user this is research assistance, not \
legal advice, only if explicitly asked for advice. Otherwise, no disclaimer.
"""


def _format_chunk_as_context(chunk: RetrievedChunk, number: int) -> str:
    """Format a single chunk as a numbered context block.

    The numbering passed in here becomes the citation number the LLM is
    expected to use. The format puts identifying metadata up front so
    the model can distinguish between, say, IPC §392 and BNS §309 at a
    glance.
    """
    meta = chunk.metadata
    source_type = meta.get("source_type", "?")

    if source_type == "act":
        short_name = meta.get("short_name") or meta.get("act_id", "?")
        section_num = meta.get("section_number", "?")
        heading = meta.get("section_heading", "")
        header = f"[{number}] {short_name} §{section_num}"
        if heading:
            header += f" — {heading}"
    elif source_type == "judgment":
        case_name = meta.get("case_name", "Unknown case")
        citation = meta.get("citation", "")
        court = meta.get("court", "")
        year = meta.get("year", "")
        header = f"[{number}] {case_name}"
        bits = [b for b in (citation, court, str(year) if year else "") if b]
        if bits:
            header += f" ({', '.join(bits)})"
    else:
        header = f"[{number}]"

    return f"{header}\n{chunk.text}"


def build_user_prompt(query: str, chunks: list[RetrievedChunk]) -> str:
    """Compose the user message: numbered context blocks then the question.

    Chunks are 1-indexed when surfaced to the LLM — citation markers
    `[1]` through `[N]` align with chunks[0] through chunks[N-1].
    """
    if not chunks:
        # Should not happen in practice — the pipeline rejects empty
        # retrieval before reaching here. Defensive guard for tests.
        return f"QUESTION: {query}\n\n(No relevant sources were found.)"

    parts = ["SOURCES:\n"]
    for i, chunk in enumerate(chunks, start=1):
        parts.append(_format_chunk_as_context(chunk, i))
        parts.append("")  # blank line between blocks
    parts.append(f"QUESTION: {query}")
    return "\n".join(parts)


class Generator:
    """End-to-end "query + chunks -> verified answer" orchestrator.

    Does not handle retrieval (caller passes chunks) or caching (the
    pipeline layer handles that). Stateless except for the injected
    `GenerationClient`.
    """

    def __init__(self, generation_client: GenerationClient) -> None:
        self._client = generation_client

    async def generate(
        self,
        query: str,
        chunks: list[RetrievedChunk],
        max_output_tokens: int | None = None,
    ) -> VerifiedAnswer:
        import dataclasses

        user_prompt = build_user_prompt(query, chunks)

        result = await self._client.generate(
            system_instruction=SYSTEM_PROMPT,
            user_prompt=user_prompt,
            max_output_tokens=max_output_tokens,
        )

        verified = verify_and_strip(result.answer_text, chunks)
        # Splice the token counts onto the verified answer. `verify_and_strip`
        # only knows about citation parsing; tokens come from the LLM client.
        # Carrying them through to the Pipeline (and then to the QueryLogWriter
        # in Chunk 4.4) lets us surface estimated cost on the admin dashboard.
        verified = dataclasses.replace(
            verified,
            prompt_tokens=result.prompt_tokens,
            output_tokens=result.output_tokens,
        )

        logger.info(
            "generation: model=%s prompt_tokens=%s output_tokens=%s "
            "cited=%d stripped=%d",
            result.model, result.prompt_tokens, result.output_tokens,
            len(verified.used_chunks), len(verified.stripped_citation_numbers),
        )

        return verified