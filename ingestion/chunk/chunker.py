"""Token-aware chunker for normalized documents.

Strategy:
  - Acts: one chunk per section by default. If a section's text exceeds
    HARD_MAX_CHARS, split into sub-chunks on paragraph boundaries within
    the section.
  - Judgments: greedy-pack consecutive paragraphs until adding the next
    one would exceed TARGET_MAX_CHARS, then start a new chunk. Never
    splits within a paragraph unless a single paragraph exceeds HARD_MAX_CHARS.

Token counts are approximated as char_count / CHARS_PER_TOKEN. For English
legal prose this is accurate to within 10-15% — fine for chunk-size
budgeting. The chunker does not need precise tokenization; the embedder
in Chunk 2 will do that against the model's own tokenizer.

Chunk IDs are deterministic:
  - Act: `<act_id>:s<section_number>:<sub_chunk_index>`
  - Judgment: `j:<folder>:p<start>-p<end>`

Stable IDs let downstream cache invalidation key off chunk_id + corpus_version.
"""

from __future__ import annotations

from collections.abc import Iterator

try:
    from ingestion.chunk.metadata import (
        ActChunkMetadata,
        Chunk,
        JudgmentChunkMetadata,
    )
    from ingestion.normalize.schema import NormalizedAct, NormalizedJudgment
except ImportError:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from ingestion.chunk.metadata import (
        ActChunkMetadata,
        Chunk,
        JudgmentChunkMetadata,
    )
    from ingestion.normalize.schema import NormalizedAct, NormalizedJudgment


TARGET_MAX_CHARS: int = 2000
HARD_MAX_CHARS: int = 2500
MIN_CHUNK_CHARS: int = 100
CHARS_PER_TOKEN: float = 4.0


def approx_token_count(text: str) -> int:
    return max(1, round(len(text) / CHARS_PER_TOKEN))


def _split_long_section_text(text: str, max_chars: int) -> list[str]:
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    if not paragraphs:
        return [text.strip()]

    chunks: list[str] = []
    buffer = ""
    for para in paragraphs:
        candidate = f"{buffer}\n\n{para}" if buffer else para
        if len(candidate) > max_chars and buffer:
            chunks.append(buffer)
            buffer = para
        else:
            buffer = candidate
    if buffer:
        chunks.append(buffer)

    return chunks if chunks else [text.strip()]


def chunk_act(act: NormalizedAct, corpus_version: str) -> Iterator[Chunk]:
    for section in act.sections:
        full_text = section.text.strip()
        if not full_text:
            continue

        if len(full_text) <= HARD_MAX_CHARS:
            sub_texts = [full_text]
        else:
            sub_texts = _split_long_section_text(full_text, TARGET_MAX_CHARS)

        for sub_index, sub_text in enumerate(sub_texts):
            if len(sub_text) < MIN_CHUNK_CHARS and len(sub_texts) > 1:
                continue

            heading_prefix = (
                f"{section.heading}\n\n" if section.heading and sub_index == 0 else ""
            )
            display_text = heading_prefix + sub_text

            chunk_id = f"{act.act_id}:s{section.section_number}:{sub_index}"
            metadata = ActChunkMetadata(
                act_id=act.act_id,
                act_name=act.act_name,
                short_name=act.short_name,
                section_number=section.section_number,
                section_heading=section.heading,
                chapter=section.chapter,
                chapter_number=section.chapter_number,
                sub_chunk_index=sub_index,
                source_url=act.source_url,
                pdf_filename=act.pdf_filename,
            )
            yield Chunk(
                chunk_id=chunk_id,
                text=display_text,
                char_count=len(display_text),
                approx_token_count=approx_token_count(display_text),
                corpus_version=corpus_version,
                metadata=metadata,
            )


def chunk_judgment(judgment: NormalizedJudgment, corpus_version: str) -> Iterator[Chunk]:
    if not judgment.paragraphs:
        return

    buffer_texts: list[str] = []
    buffer_indices: list[int] = []
    buffer_len = 0

    def flush() -> Chunk | None:
        if not buffer_texts:
            return None
        text = "\n\n".join(buffer_texts)
        chunk_id = f"j:{judgment.folder}:p{buffer_indices[0]}-p{buffer_indices[-1]}"
        metadata = JudgmentChunkMetadata(
            folder=judgment.folder,
            case_id=judgment.case_id,
            case_name=judgment.case_name,
            citation=judgment.citation,
            court=judgment.court,
            year=judgment.year,
            primary_section=judgment.primary_section,
            other_sections=judgment.other_sections,
            outcome=judgment.outcome,
            indian_kanoon_url=judgment.indian_kanoon_url,
            pdf_filename=judgment.pdf_filename,
            html_filename=judgment.html_filename,
            paragraph_start=buffer_indices[0],
            paragraph_end=buffer_indices[-1],
        )
        return Chunk(
            chunk_id=chunk_id,
            text=text,
            char_count=len(text),
            approx_token_count=approx_token_count(text),
            corpus_version=corpus_version,
            metadata=metadata,
        )

    for para in judgment.paragraphs:
        para_text = para.text.strip()
        if not para_text:
            continue

        prospective_len = buffer_len + (2 if buffer_texts else 0) + len(para_text)

        if buffer_texts and prospective_len > TARGET_MAX_CHARS:
            chunk = flush()
            if chunk is not None:
                yield chunk
            buffer_texts = []
            buffer_indices = []
            buffer_len = 0

        if len(para_text) > HARD_MAX_CHARS:
            for piece in _split_long_section_text(para_text, TARGET_MAX_CHARS):
                buffer_texts = [piece]
                buffer_indices = [para.paragraph_index]
                buffer_len = len(piece)
                chunk = flush()
                if chunk is not None:
                    yield chunk
            buffer_texts = []
            buffer_indices = []
            buffer_len = 0
            continue

        buffer_texts.append(para_text)
        buffer_indices.append(para.paragraph_index)
        buffer_len += len(para_text) + (2 if len(buffer_texts) > 1 else 0)

    chunk = flush()
    if chunk is not None:
        yield chunk