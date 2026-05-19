"""Extract clean paragraph-level text from an Indian Kanoon judgment HTML file.

Indian Kanoon serves judgments wrapped in <div class="judgments"> with each
paragraph as a <p>. We strip site chrome (scripts, styles, nav, headers,
footers, citation widgets), pull the judgment body, and return one
JudgmentParagraph per <p> tag with non-empty text.

If the canonical container is missing (older pages, edge cases), we fall
back to the largest contiguous block of <p> tags in <body>. Parse warnings
are accumulated and surface on the NormalizedJudgment.parse_warnings field.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from bs4 import BeautifulSoup, Tag


JUDGMENT_CONTAINER_CLASSES: tuple[str, ...] = ("judgments", "judgment")
NOISE_TAGS: tuple[str, ...] = ("script", "style", "noscript", "nav", "header", "footer", "form", "iframe")
NOISE_CLASS_SUBSTRINGS: tuple[str, ...] = (
    "ad",
    "advertisement",
    "share",
    "navigation",
    "breadcrumb",
    "sidebar",
    "menu",
    "social",
)
MIN_PARAGRAPH_CHARS: int = 30
MIN_BODY_PARAGRAPHS: int = 3
WHITESPACE_RE: re.Pattern[str] = re.compile(r"\s+")

logger = logging.getLogger(__name__)


@dataclass
class ExtractedJudgment:
    paragraphs: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def normalize_whitespace(text: str) -> str:
    return WHITESPACE_RE.sub(" ", text).strip()


def strip_noise(soup: BeautifulSoup) -> None:
    for tag_name in NOISE_TAGS:
        for tag in soup.find_all(tag_name):
            tag.decompose()

    # bs4 with lxml can produce tags whose .attrs is None when parsing
    # malformed Indian Kanoon HTML. That breaks soup.find_all(class_=True)
    # itself, because internally bs4 calls tag.get("class") which dereferences
    # tag.attrs.get(...). To avoid the crash, iterate every tag and inspect
    # attrs defensively rather than asking bs4 to filter for us.
    for tag in soup.find_all(True):
        attrs = getattr(tag, "attrs", None)
        if not attrs:
            continue
        classes = attrs.get("class") or []
        if isinstance(classes, str):
            classes = [classes]
        if not classes:
            continue
        combined = " ".join(classes).lower()
        if any(needle in combined for needle in NOISE_CLASS_SUBSTRINGS):
            tag.decompose()


def find_judgment_container(soup: BeautifulSoup) -> Tag | None:
    for class_name in JUDGMENT_CONTAINER_CLASSES:
        container = soup.find(class_=class_name)
        if isinstance(container, Tag):
            return container
    return None


def collect_paragraphs(container: Tag) -> list[str]:
    paragraphs: list[str] = []
    for tag in container.find_all(["p", "blockquote"]):
        text = normalize_whitespace(tag.get_text(separator=" "))
        if len(text) >= MIN_PARAGRAPH_CHARS:
            paragraphs.append(text)
    return paragraphs


def fallback_collect_body_paragraphs(soup: BeautifulSoup) -> list[str]:
    body = soup.find("body")
    if not isinstance(body, Tag):
        return []
    return collect_paragraphs(body)


def extract_judgment(html_path: Path) -> ExtractedJudgment:
    result = ExtractedJudgment()

    try:
        raw_html = html_path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        result.warnings.append(f"failed to read file: {e}")
        return result

    soup = BeautifulSoup(raw_html, "html.parser")
    strip_noise(soup)

    container = find_judgment_container(soup)
    if container is None:
        result.warnings.append(
            "no canonical judgment container found; falling back to body-wide paragraph scan"
        )
        paragraphs = fallback_collect_body_paragraphs(soup)
    else:
        paragraphs = collect_paragraphs(container)

    if len(paragraphs) < MIN_BODY_PARAGRAPHS:
        result.warnings.append(
            f"extracted only {len(paragraphs)} paragraph(s); judgment body may be incomplete or malformed"
        )

    if not paragraphs:
        result.warnings.append("extraction produced zero paragraphs")
        return result

    result.paragraphs = paragraphs
    return result