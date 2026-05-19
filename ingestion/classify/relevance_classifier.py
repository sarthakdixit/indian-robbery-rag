"""Classify a single judgment for robbery relevance via Gemini.

Exposes one entry point: `classify_judgment_html`. Reads an HTML file,
extracts a brief excerpt, sends a request to Gemini with a Pydantic
response schema, and returns a validated ClassifierVerdict.

Sync only — ingestion scripts run offline as batch work (AGENT.md 7.2).
Uses the modern `google-genai` SDK (not the deprecated `google.generativeai`).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from bs4 import BeautifulSoup
from google import genai  # type: ignore[import-untyped]
from google.genai import types as genai_types  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field, ValidationError

try:
    from ingestion.classify.prompts import (
        EXCERPT_MAX_CHARS,
        SYSTEM_PROMPT,
        USER_PROMPT_TEMPLATE,
    )
except ImportError:
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from prompts import EXCERPT_MAX_CHARS, SYSTEM_PROMPT, USER_PROMPT_TEMPLATE


GEMINI_MODEL_FOR_CLASSIFICATION: str = "gemini-2.5-flash-lite"

# Gemini API uses a restricted JSON Schema subset (OpenAPI-style) and rejects
# Pydantic's auto-generated schema because it contains `additionalProperties`.
# Build the schema by hand using only the fields Gemini's validator accepts:
# https://ai.google.dev/api/caching#Schema
CLASSIFIER_RESPONSE_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "is_relevant": {
            "type": "boolean",
            "description": "True if the judgment is substantively about robbery under "
            "IPC §§390-402 or BNS §§309-311.",
        },
        "relevance_score": {
            "type": "number",
            "description": "Confidence score from 0.0 (clearly off-topic) to 1.0 "
            "(clearly on-topic).",
        },
        "reasoning": {
            "type": "string",
            "description": "One-sentence justification for the verdict.",
        },
    },
    "required": ["is_relevant", "relevance_score", "reasoning"],
}

logger = logging.getLogger(__name__)


class ClassifierVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    is_relevant: bool
    relevance_score: float = Field(ge=0.0, le=1.0)
    reasoning: str = Field(min_length=1, max_length=500)


@dataclass(frozen=True)
class JudgmentContext:
    case_name: str
    citation: str
    court: str
    year: int
    primary_section: str
    html_path: Path


@dataclass(frozen=True)
class ClassificationFailure:
    reason: str


ClassificationResult = ClassifierVerdict | ClassificationFailure


def extract_judgment_excerpt(html_path: Path, max_chars: int = EXCERPT_MAX_CHARS) -> str:
    raw_html = html_path.read_text(encoding="utf-8", errors="replace")
    soup = BeautifulSoup(raw_html, "html.parser")

    for tag in soup(["script", "style", "noscript", "nav", "header", "footer"]):
        tag.decompose()

    text = soup.get_text(separator=" ", strip=True)
    text = " ".join(text.split())

    if len(text) <= max_chars:
        return text
    return text[:max_chars].rsplit(" ", 1)[0] + " ..."


def build_user_prompt(context: JudgmentContext, excerpt: str) -> str:
    return USER_PROMPT_TEMPLATE.format(
        case_name=context.case_name,
        citation=context.citation,
        court=context.court,
        year=context.year,
        primary_section=context.primary_section,
        excerpt_chars=EXCERPT_MAX_CHARS,
        excerpt=excerpt,
    )


def parse_classifier_response(raw_response: str) -> ClassifierVerdict | None:
    try:
        return ClassifierVerdict.model_validate_json(raw_response)
    except ValidationError as e:
        logger.warning("Classifier response failed schema validation: %s", e.errors())
        return None


def classify_judgment_html(
    context: JudgmentContext,
    api_key: str,
    model_name: str = GEMINI_MODEL_FOR_CLASSIFICATION,
) -> ClassificationResult:
    if not context.html_path.is_file():
        return ClassificationFailure(reason=f"HTML not found at {context.html_path}")

    try:
        excerpt = extract_judgment_excerpt(context.html_path)
    except OSError as e:
        return ClassificationFailure(reason=f"failed to read HTML: {e}")

    if len(excerpt) < 200:
        return ClassificationFailure(
            reason=f"excerpt too short ({len(excerpt)} chars) — HTML may be malformed"
        )

    client = genai.Client(api_key=api_key)
    config = genai_types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        temperature=0.1,
        max_output_tokens=300,
        response_mime_type="application/json",
        response_schema=CLASSIFIER_RESPONSE_SCHEMA,
    )

    prompt = build_user_prompt(context, excerpt)
    try:
        response = client.models.generate_content(
            model=model_name,
            contents=prompt,
            config=config,
        )
    except Exception as e:
        return ClassificationFailure(reason=f"Gemini call failed: {type(e).__name__}: {e}")

    raw_text = (getattr(response, "text", "") or "").strip()
    if not raw_text:
        return ClassificationFailure(reason="Gemini returned empty response")

    verdict = parse_classifier_response(raw_text)
    if verdict is None:
        return ClassificationFailure(
            reason=f"Gemini response did not match expected JSON schema; raw: {raw_text[:200]!r}"
        )
    return verdict