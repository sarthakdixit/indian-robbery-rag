from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ChunkSourceType(str, Enum):
    ACT = "act"
    JUDGMENT = "judgment"


class ActChunkMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    source_type: Literal[ChunkSourceType.ACT] = ChunkSourceType.ACT
    act_id: str
    act_name: str
    short_name: str
    section_number: str
    section_heading: str | None = None
    chapter: str | None = None
    chapter_number: str | None = None
    sub_chunk_index: int = Field(ge=0)
    source_url: str
    pdf_filename: str


class JudgmentChunkMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    source_type: Literal[ChunkSourceType.JUDGMENT] = ChunkSourceType.JUDGMENT
    folder: str
    case_id: str
    case_name: str
    citation: str
    court: str
    year: int
    primary_section: str
    other_sections: list[str]
    outcome: str
    indian_kanoon_url: str
    pdf_filename: str
    html_filename: str
    paragraph_start: int = Field(ge=0)
    paragraph_end: int = Field(ge=0)


ChunkMetadata = ActChunkMetadata | JudgmentChunkMetadata


class Chunk(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    chunk_id: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1)
    char_count: int = Field(ge=1)
    approx_token_count: int = Field(ge=1)
    corpus_version: str = Field(min_length=1)
    metadata: ChunkMetadata