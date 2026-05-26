"""Gemini API adapters for the backend.

Exports two async adapters:

  - `GeminiEmbeddingsAdapter` — `EmbeddingsClient` protocol; query-time
    embedding with `task_type=RETRIEVAL_QUERY`.
  - `GeminiGenerationAdapter` — `GenerationClient` protocol; the answer
    LLM (gemini-2.5-flash-lite by default).

Both adapters:
  - Use the async surface (`client.aio.models.*`) per AGENT.md §7.
  - Raise typed exceptions on failure (`GeminiEmbeddingsError`,
    `GeminiGenerationError`, `GeminiQuotaExhausted`).
  - Share the `_is_quota_error` heuristic for detecting 429 responses,
    and the same `GeminiQuotaExhausted` exception type so the FastAPI
    error handler can catch both with one `except` clause.

The Matryoshka normalization quirk applies only to embeddings: when we
request 768-dim instead of the native 3072, the API returns unnormalized
vectors and we L2-normalize at the client boundary.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from google import genai  # type: ignore[import-untyped]
from google.genai import types as genai_types  # type: ignore[import-untyped]

from backend.app.protocols.generation import GenerationResult

if TYPE_CHECKING:
    from backend.app.config import Settings


logger = logging.getLogger(__name__)


# Exception hierarchy.
#
# Two adapter-specific error types (one for embeddings, one for generation)
# plus a shared quota subclass that the HTTP layer can catch with a single
# `except` clause regardless of which adapter raised it. Quota always maps
# to HTTP 503; the other errors map to 500 for the user but log with
# adapter-specific context for our diagnostics.
class GeminiEmbeddingsError(Exception):
    """Wraps an unexpected failure from the Gemini embeddings API."""


class GeminiGenerationError(Exception):
    """Wraps an unexpected failure from the Gemini generation API."""


class GeminiQuotaExhausted(GeminiEmbeddingsError, GeminiGenerationError):
    """Either embeddings or generation quota has been hit (HTTP 503).

    Multiple inheritance is deliberate: lets callers catch either
    `GeminiEmbeddingsError` or `GeminiGenerationError` and pick up the
    quota case in the same `except`, while also letting the top-level
    handler use `except GeminiQuotaExhausted` to route to a 503.
    """


def _normalize_inplace(vec: list[float]) -> list[float]:
    """L2-normalize to unit length. Returns the same list, mutated."""
    norm_sq = sum(x * x for x in vec)
    if norm_sq <= 0.0:
        return vec
    inv_norm = 1.0 / (norm_sq ** 0.5)
    for i, x in enumerate(vec):
        vec[i] = x * inv_norm
    return vec


def _is_quota_error(exc: Exception) -> bool:
    """Heuristic: does this exception look like a Gemini 429?"""
    msg = f"{type(exc).__name__}: {exc}"
    return any(
        token in msg
        for token in ("RESOURCE_EXHAUSTED", "429", "exceeded your current quota")
    )


class GeminiEmbeddingsAdapter:
    """Async adapter implementing the `EmbeddingsClient` protocol.

    Constructed by the DI container with a Settings instance. The
    underlying `genai.Client` is created once and reused for every
    embed_query call.

    Concurrency: the genai client is safe to share across coroutines;
    httpx (the default transport) maintains an internal connection pool.
    """

    def __init__(self, settings: Settings) -> None:
        self._model = settings.gemini_embedding_model
        self._dim = settings.gemini_embedding_dimensions
        # The 3072-dim native output is already normalized; lower dims are
        # MRL truncations and need explicit normalization (see Batch 2.1
        # README for the reference and a worked example).
        self._requires_normalization = self._dim < 3072
        self._client = genai.Client(api_key=settings.gemini_api_key.get_secret_value())

    async def embed_query(self, query: str) -> list[float]:
        if not query or not query.strip():
            raise GeminiEmbeddingsError("embed_query called with empty query")

        config = genai_types.EmbedContentConfig(
            task_type="RETRIEVAL_QUERY",
            output_dimensionality=self._dim,
        )

        try:
            response = await self._client.aio.models.embed_content(
                model=self._model,
                contents=[query],
                config=config,
            )
        except Exception as e:
            if _is_quota_error(e):
                raise GeminiQuotaExhausted(
                    f"Gemini embeddings quota exhausted: {type(e).__name__}: {e}"
                ) from e
            raise GeminiEmbeddingsError(
                f"Gemini embeddings call failed: {type(e).__name__}: {e}"
            ) from e

        embeddings = getattr(response, "embeddings", None)
        if not embeddings or len(embeddings) != 1:
            raise GeminiEmbeddingsError(
                f"Gemini returned {len(embeddings) if embeddings else 0} embeddings; expected 1"
            )

        values = getattr(embeddings[0], "values", None)
        if not isinstance(values, list) or len(values) != self._dim:
            got = len(values) if isinstance(values, list) else "non-list"
            raise GeminiEmbeddingsError(
                f"Gemini embedding has shape {got}, expected list of length {self._dim}"
            )

        if self._requires_normalization:
            _normalize_inplace(values)

        return values

class GeminiGenerationAdapter:
    """Async adapter implementing the `GenerationClient` protocol.

    Uses `gemini-2.5-flash-lite` by default (configurable via Settings).
    Temperature is held low (0.2) because legal Q&A wants determinism,
    not creativity — we'd rather get the same answer twice than a
    different-but-plausible answer the second time.

    Concurrency: the underlying `genai.Client` is safe to share across
    coroutines; httpx maintains an internal connection pool.
    """

    # Sensible defaults baked in. They're not user-tunable through
    # Settings because changing them invalidates eval-set results; if
    # we ever want to A/B test, we'll wire them through Settings then.
    _TEMPERATURE: float = 0.2
    _DEFAULT_MAX_OUTPUT_TOKENS: int = 1024

    def __init__(self, settings: Settings) -> None:
        self._model = settings.gemini_generation_model
        self._client = genai.Client(api_key=settings.gemini_api_key.get_secret_value())

    async def generate(
        self,
        system_instruction: str,
        user_prompt: str,
        max_output_tokens: int | None = None,
    ) -> GenerationResult:
        if not user_prompt or not user_prompt.strip():
            raise GeminiGenerationError("generate called with empty user_prompt")

        config = genai_types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=self._TEMPERATURE,
            max_output_tokens=max_output_tokens or self._DEFAULT_MAX_OUTPUT_TOKENS,
        )

        try:
            response = await self._client.aio.models.generate_content(
                model=self._model,
                contents=user_prompt,
                config=config,
            )
        except Exception as e:
            if _is_quota_error(e):
                raise GeminiQuotaExhausted(
                    f"Gemini generation quota exhausted: {type(e).__name__}: {e}"
                ) from e
            raise GeminiGenerationError(
                f"Gemini generation call failed: {type(e).__name__}: {e}"
            ) from e

        # Extract the text. The SDK's `.text` property concatenates parts
        # for us, but it can be missing or empty if the model refused or
        # the response was truncated. We treat empty output as a soft
        # error rather than crashing the user — the pipeline can still
        # decide what to do (return a "sorry, I cannot answer" response).
        answer_text = getattr(response, "text", None) or ""
        if not answer_text.strip():
            raise GeminiGenerationError(
                "Gemini returned empty response text; "
                f"finish_reason={getattr(response, 'candidates', [None])[0] if response else None}"
            )

        # Token counts are best-effort — the SDK doesn't always populate
        # them depending on streaming / safety filters. None is fine
        # downstream; we just won't have cost data for that request.
        prompt_tokens = None
        output_tokens = None
        usage = getattr(response, "usage_metadata", None)
        if usage is not None:
            prompt_tokens = getattr(usage, "prompt_token_count", None)
            output_tokens = getattr(usage, "candidates_token_count", None)

        return GenerationResult(
            answer_text=answer_text,
            model=self._model,
            prompt_tokens=prompt_tokens,
            output_tokens=output_tokens,
        )