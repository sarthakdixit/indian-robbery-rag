"""Gemini embeddings client.

Wraps `client.models.embed_content` from the google-genai SDK. Adds:

  - Batching at MAX_BATCH_SIZE = 100 (the API's per-request cap)
  - Quota-aware error detection (returns a sentinel rather than raising
    on RESOURCE_EXHAUSTED, so the caller can stop cleanly and resume on
    the next run after quota reset)
  - Defensive validation of response shape and dimensionality
  - Task-typed embeddings (RETRIEVAL_DOCUMENT for ingestion;
    RETRIEVAL_QUERY for query-time embedding in the backend)

The asymmetric task types matter: Gemini's embedding model produces
slightly different vectors depending on the declared task, and matching
RETRIEVAL_QUERY against RETRIEVAL_DOCUMENT at search time improves
relevance materially. The ingestion script always uses
RETRIEVAL_DOCUMENT; the backend's query-time embedder (built in
Batch 3) will use RETRIEVAL_QUERY.

Sync only — ingestion is offline batch work (AGENT.md 7.2).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from google import genai  # type: ignore[import-untyped]
from google.genai import types as genai_types  # type: ignore[import-untyped]


GEMINI_EMBEDDING_MODEL: str = "gemini-embedding-001"

# text-embedding-004 was deprecated on January 14, 2026; gemini-embedding-001
# is its successor. The new model defaults to 3072 dimensions but supports
# Matryoshka Representation Learning truncation to any of 768/1536/3072. We
# pick 768 to match our previous index dimensionality, keep ChromaDB queries
# cheap, and avoid bloating the persisted index by 4x.
EMBEDDING_DIM: int = 768

# The API caps a single batched request at 20,000 input tokens (across all
# inputs) and 250 individual inputs. At our chunker's TARGET_MAX_CHARS = 2000
# (~500 tokens) with an outlier max around 5300 chars (~1325 tokens), a batch
# of 100 chunks could hit ~25,000-50,000 tokens — over the cap. Batch size
# 50 with avg ~500 tokens/chunk = ~25,000 tokens; with conservative chunks
# averaging closer to 250 tokens = ~12,500 tokens, well under the cap.
MAX_BATCH_SIZE: int = 50

TaskType = Literal["RETRIEVAL_DOCUMENT", "RETRIEVAL_QUERY", "SEMANTIC_SIMILARITY"]

QUOTA_EXHAUSTED_FINGERPRINTS: tuple[str, ...] = (
    "RESOURCE_EXHAUSTED",
    "429",
    "exceeded your current quota",
)

# gemini-embedding-001 only returns L2-normalized vectors at its native
# 3072-dim output. When we ask for a Matryoshka-truncated dimension like
# 768, the truncated vector is NOT normalized — its L2 norm is typically
# ~0.5 to ~0.7. Per Google's documentation:
#
#     "For other dimensions, including 768 and 1536, you need to
#      normalize the embeddings."
#
# We normalize at the client boundary so every downstream consumer
# (ChromaDB, the semantic cache, the scope-rejection threshold) can
# safely assume unit norm. Cosine similarity == dot product on
# normalized vectors, which simplifies the math everywhere downstream.
REQUIRES_NORMALIZATION: bool = EMBEDDING_DIM < 3072

logger = logging.getLogger(__name__)


def _normalize_inplace(vec: list[float]) -> list[float]:
    """L2-normalize a vector to unit length. Returns the same list, mutated."""
    norm_sq = sum(x * x for x in vec)
    if norm_sq <= 0.0:
        # Zero vector — pathological, but bail rather than divide by zero.
        # Caller treats this as an EmbeddingsError elsewhere.
        return vec
    inv_norm = 1.0 / (norm_sq ** 0.5)
    for i, x in enumerate(vec):
        vec[i] = x * inv_norm
    return vec


@dataclass(frozen=True)
class EmbeddingsOk:
    vectors: list[list[float]]


@dataclass(frozen=True)
class QuotaExhausted:
    retry_after_seconds: float | None
    raw_error: str


@dataclass(frozen=True)
class EmbeddingsError:
    raw_error: str


EmbeddingsResult = EmbeddingsOk | QuotaExhausted | EmbeddingsError


def _looks_like_quota_error(error_str: str) -> bool:
    return any(token in error_str for token in QUOTA_EXHAUSTED_FINGERPRINTS)


def _extract_retry_after(error_str: str) -> float | None:
    """Pull the retry_after seconds out of a Gemini 429 error string, best-effort.

    Returns None if no retry_after pattern is detectable. The orchestrator
    treats this as 'unknown'; quota typically resets at midnight Pacific.
    """
    import re
    match = re.search(r"retry in ([\d.]+)s", error_str)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            return None
    return None


class GeminiEmbeddingsClient:
    """Sync wrapper around `client.models.embed_content`."""

    def __init__(
        self,
        api_key: str,
        model: str = GEMINI_EMBEDDING_MODEL,
        task_type: TaskType = "RETRIEVAL_DOCUMENT",
    ) -> None:
        if not api_key:
            raise ValueError("api_key is required")
        self._model = model
        self._task_type = task_type
        self._client = genai.Client(api_key=api_key)

    @property
    def model(self) -> str:
        return self._model

    @property
    def task_type(self) -> str:
        return self._task_type

    def embed_batch(self, texts: list[str]) -> EmbeddingsResult:
        """Embed up to MAX_BATCH_SIZE texts in a single API call.

        Returns one of:
          - EmbeddingsOk with `vectors` parallel to input `texts`
          - QuotaExhausted if Gemini returned a quota 429
          - EmbeddingsError for any other failure mode

        Empty input is rejected. Inputs larger than MAX_BATCH_SIZE are
        rejected; the caller should chunk first.
        """
        if not texts:
            return EmbeddingsError(raw_error="embed_batch called with empty input")
        if len(texts) > MAX_BATCH_SIZE:
            return EmbeddingsError(
                raw_error=f"batch size {len(texts)} exceeds MAX_BATCH_SIZE {MAX_BATCH_SIZE}"
            )

        config = genai_types.EmbedContentConfig(
            task_type=self._task_type,
            output_dimensionality=EMBEDDING_DIM,
        )

        try:
            response = self._client.models.embed_content(
                model=self._model,
                contents=texts,
                config=config,
            )
        except Exception as e:
            error_str = f"{type(e).__name__}: {e}"
            if _looks_like_quota_error(error_str):
                return QuotaExhausted(
                    retry_after_seconds=_extract_retry_after(error_str),
                    raw_error=error_str,
                )
            return EmbeddingsError(raw_error=error_str)

        embeddings = getattr(response, "embeddings", None)
        if embeddings is None or len(embeddings) != len(texts):
            return EmbeddingsError(
                raw_error=(
                    f"response shape mismatch: requested {len(texts)} embeddings, "
                    f"got {len(embeddings) if embeddings else 0}"
                )
            )

        vectors: list[list[float]] = []
        for i, emb in enumerate(embeddings):
            values = getattr(emb, "values", None)
            if values is None or not isinstance(values, list):
                return EmbeddingsError(
                    raw_error=f"embedding {i} missing .values field or wrong type"
                )
            if len(values) != EMBEDDING_DIM:
                return EmbeddingsError(
                    raw_error=(
                        f"embedding {i} has dim={len(values)}, expected {EMBEDDING_DIM}"
                    )
                )
            # MRL-truncated vectors come back unnormalized. Normalize at the
            # client boundary so callers see unit-norm vectors regardless of
            # which output dimension we requested.
            if REQUIRES_NORMALIZATION:
                values = _normalize_inplace(list(values))
            vectors.append(values)

        return EmbeddingsOk(vectors=vectors)