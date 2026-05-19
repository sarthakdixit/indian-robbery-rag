from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SourceType(str, Enum):
    ACT = "act"
    JUDGMENT = "judgment"


class ActSection(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    section_number: str = Field(min_length=1, max_length=20)
    heading: str | None = Field(default=None, max_length=300)
    text: str = Field(min_length=1)
    chapter: str | None = Field(default=None, max_length=200)
    chapter_number: str | None = Field(default=None, max_length=20)


class NormalizedAct(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    source_type: Literal[SourceType.ACT] = SourceType.ACT
    act_id: str = Field(min_length=1, max_length=50)
    act_name: str = Field(min_length=1, max_length=200)
    short_name: str = Field(min_length=1, max_length=20)
    source_url: str
    pdf_filename: str
    sections: list[ActSection]
    parse_warnings: list[str] = Field(default_factory=list)


class JudgmentParagraph(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    paragraph_index: int = Field(ge=0)
    text: str = Field(min_length=1)


class NormalizedJudgment(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    source_type: Literal[SourceType.JUDGMENT] = SourceType.JUDGMENT
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
    paragraphs: list[JudgmentParagraph]
    parse_warnings: list[str] = Field(default_factory=list)


NormalizedDocument = NormalizedAct | NormalizedJudgment