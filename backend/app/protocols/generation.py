"""Protocol for the generation-side LLM client.

The retrieval side has its own protocols (see `protocols/retrieval.py`).
The generation client is separate because it's used by a different stage
of the pipeline and has different quota dynamics — generation quota is
the scarce one (~20/day free tier for gemini-2.5-flash-lite), and our
HTTP-layer error mapping treats generation quota as a 503 (service
unavailable) rather than the 500 we'd return for an unexpected error.

The Protocol takes a system instruction and user prompt separately
rather than a flat string. This matches the underlying Gemini API
(which has dedicated system_instruction support) and lets us version
the system prompt independently of the per-request user prompt.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class GenerationResult:
    """A single generation response.

    `answer_text` is the LLM's raw output, with citation markers like
    `[1]` and `[2]` still inline. Downstream code parses these and
    validates them against the retrieved chunks before returning the
    response to the user.

    `prompt_tokens` and `output_tokens` are optional — the SDK reports
    them when available but we don't fail if they're absent. They're
    useful for the admin dashboard's cost tracker (Batch 5) but not
    required for the answer itself.

    `model` records which model produced this output. Useful for the
    admin dashboard and for downstream debugging when we A/B test
    different models.
    """

    answer_text: str
    model: str
    prompt_tokens: int | None = None
    output_tokens: int | None = None


class GenerationClient(Protocol):
    """LLM generation client.

    Implementations should be safe to share across coroutines (the
    Gemini client's httpx transport handles this internally).
    """

    async def generate(
        self,
        system_instruction: str,
        user_prompt: str,
        max_output_tokens: int | None = None,
    ) -> GenerationResult:
        """Generate a single response.

        Raises a typed exception subclass (`GeminiGenerationError`,
        `GeminiQuotaExhausted`) on failure rather than returning a
        sentinel. The pipeline's outer FastAPI handler translates these
        to HTTP error responses (see `errors.py` and `routes/query.py`
        in Batch 4).
        """
        ...