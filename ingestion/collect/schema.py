from __future__ import annotations

import re
from datetime import date
from enum import Enum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


FILENAME_PATTERN = re.compile(r"^[a-z0-9_]+\.(html|pdf)$")
FOLDER_NUMBER_PATTERN = re.compile(r"^\d{2,}$")
SHA256_PATTERN = re.compile(r"^[a-f0-9]{64}$")


class Outcome(str, Enum):
    CONVICTION_UPHELD = "conviction-upheld"
    CONVICTION_SET_ASIDE = "conviction-set-aside"
    BAIL_GRANTED = "bail-granted"
    BAIL_DENIED = "bail-denied"
    OTHER = "other"


class RelevanceStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    NEEDS_REVIEW = "needs-review"


class ActManifestEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    act_id: str = Field(min_length=1, max_length=50, pattern=r"^[a-z0-9_]+$")
    act_name: str = Field(min_length=1, max_length=200)
    short_name: str = Field(min_length=1, max_length=20)
    filename: str = Field(min_length=1, max_length=200)
    source_url: str = Field(min_length=1)
    retrieved_date: date
    sha256: str | None = None

    @field_validator("filename")
    @classmethod
    def filename_must_be_normalized_pdf(cls, value: str) -> str:
        if not FILENAME_PATTERN.match(value):
            raise ValueError(
                f"filename {value!r} must be lowercase, underscores only, with .html or .pdf extension"
            )
        if not value.endswith(".pdf"):
            raise ValueError(f"act filename {value!r} must end with .pdf (acts are PDFs only)")
        return value

    @field_validator("sha256")
    @classmethod
    def sha256_must_be_hex_or_null(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not SHA256_PATTERN.match(value):
            raise ValueError(f"sha256 {value!r} must be 64 lowercase hex chars or null")
        return value


class JudgmentManifestEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    folder: str = Field(min_length=2, max_length=4)
    case_id: str = Field(min_length=1, max_length=100)
    case_name: str = Field(min_length=1, max_length=300)
    citation: str = Field(min_length=1, max_length=300)
    court: str = Field(min_length=1, max_length=100)
    year: int = Field(ge=1860, le=2100)
    primary_section: str = Field(min_length=1, max_length=50)
    other_sections: list[str] = Field(default_factory=list)
    outcome: Outcome
    indian_kanoon_url: str = Field(min_length=1)
    indian_kanoon_doc_id: str | None = None
    html_filename: str = Field(min_length=1, max_length=200)
    pdf_filename: str = Field(min_length=1, max_length=200)
    retrieved_date: date
    html_sha256: str | None = None
    pdf_sha256: str | None = None
    relevance_classifier_status: RelevanceStatus = RelevanceStatus.PENDING
    relevance_score: float | None = Field(default=None, ge=0.0, le=1.0)
    classifier_reasoning: str | None = None
    manual_review_notes: str | None = None

    @field_validator("folder")
    @classmethod
    def folder_must_be_numeric(cls, value: str) -> str:
        if not FOLDER_NUMBER_PATTERN.match(value):
            raise ValueError(f"folder {value!r} must be a zero-padded number (e.g. '01', '02', '10', '70')")
        return value

    @field_validator("html_filename")
    @classmethod
    def html_filename_must_be_normalized_html(cls, value: str) -> str:
        if not FILENAME_PATTERN.match(value):
            raise ValueError(
                f"html_filename {value!r} must be lowercase, underscores only, with .html extension"
            )
        if not value.endswith(".html"):
            raise ValueError(f"html_filename {value!r} must end with .html")
        return value

    @field_validator("pdf_filename")
    @classmethod
    def pdf_filename_must_be_normalized_pdf(cls, value: str) -> str:
        if not FILENAME_PATTERN.match(value):
            raise ValueError(
                f"pdf_filename {value!r} must be lowercase, underscores only, with .pdf extension"
            )
        if not value.endswith(".pdf"):
            raise ValueError(f"pdf_filename {value!r} must end with .pdf")
        return value

    @field_validator("html_sha256", "pdf_sha256")
    @classmethod
    def hashes_must_be_hex_or_null(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not SHA256_PATTERN.match(value):
            raise ValueError(f"sha256 {value!r} must be 64 lowercase hex chars or null")
        return value

    def html_path(self, data_root: Path) -> Path:
        return data_root / self.folder / self.html_filename

    def pdf_path(self, data_root: Path) -> Path:
        return data_root / self.folder / self.pdf_filename

    def has_matching_base_names(self) -> bool:
        return Path(self.html_filename).stem == Path(self.pdf_filename).stem


class SourcesManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    corpus_version: str = Field(min_length=1, max_length=50, pattern=r"^[\d.\-_]+$")
    schema_version: Literal["1"] = "1"
    acts: list[ActManifestEntry]
    judgments: list[JudgmentManifestEntry]

    @field_validator("judgments")
    @classmethod
    def judgment_folders_must_be_unique(
        cls, value: list[JudgmentManifestEntry]
    ) -> list[JudgmentManifestEntry]:
        folders = [j.folder for j in value]
        duplicates = [f for f in set(folders) if folders.count(f) > 1]
        if duplicates:
            raise ValueError(f"duplicate folder numbers in judgments: {sorted(duplicates)}")
        return value

    @field_validator("acts")
    @classmethod
    def act_ids_must_be_unique(cls, value: list[ActManifestEntry]) -> list[ActManifestEntry]:
        act_ids = [a.act_id for a in value]
        duplicates = [a for a in set(act_ids) if act_ids.count(a) > 1]
        if duplicates:
            raise ValueError(f"duplicate act_id in acts: {sorted(duplicates)}")
        return value

    def approved_judgments(self) -> list[JudgmentManifestEntry]:
        return [j for j in self.judgments if j.relevance_classifier_status == RelevanceStatus.APPROVED]

    def pending_judgments(self) -> list[JudgmentManifestEntry]:
        return [j for j in self.judgments if j.relevance_classifier_status == RelevanceStatus.PENDING]