"""Tunable constants for the RAG pipeline.

Per AGENT.md §15.1, every threshold and magic number lives in a
`constants.py` within its owning package. Bumping one of these is a
single-line change with a clear audit trail. Several of these have NOT
been empirically tuned yet — they're conservative defaults documented
as such, with eval-set-driven re-tuning planned in Batch 8.
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# Retrieval depth.
# ---------------------------------------------------------------------------
# Each retriever (vector, BM25) pulls this many candidates. The fused list
# is then truncated to RETRIEVAL_FINAL_K before being sent to the LLM.
# Larger TOP_K gives RRF more material to work with at the cost of slightly
# more compute. Final K is bounded by the LLM's context budget — 5 chunks
# of ~500 tokens each = 2500 tokens of context, comfortable for any model.
RETRIEVAL_TOP_K: int = 20
RETRIEVAL_FINAL_K: int = 5


# ---------------------------------------------------------------------------
# Reciprocal Rank Fusion.
# ---------------------------------------------------------------------------
# RRF fuses two ranked lists by summing 1 / (k + rank_in_list_i) across
# retrievers. The constant k dampens the influence of top ranks: higher k
# means rank 1 and rank 2 are valued more similarly. k=60 is the value
# from the original Cormack et al. paper and has become the de-facto
# default across LlamaIndex, LangChain, and similar libraries.
#
# Rationale for RRF over weighted sum:
#  - No score-magnitude calibration needed (BM25 is unbounded; cosine is [0,1])
#  - Degrades gracefully when one retriever returns no results for a chunk
#    (the index is currently partial, so this happens frequently in dev)
#  - Standard practice; easy to re-tune later with a real eval set
RRF_K: int = 60


# ---------------------------------------------------------------------------
# Scope rejection threshold.
# ---------------------------------------------------------------------------
# After retrieval, if the top vector cosine similarity is below this
# threshold the query is rejected as out-of-scope before being sent to
# the generation LLM. This protects the (tight) LLM quota from being
# burned on questions like "best pizza in Mumbai."
#
# Empirical calibration (scripts/measure_scope_threshold.py, 2026-06-02,
# against 954-chunk index, gemini-embedding-001):
#   - 12 hand-curated in-scope queries: range [0.694, 0.781], median 0.724
#   - 12 hand-curated OOS queries: range [0.515, 0.559], median 0.531
#   - Gap: 0.135 (in-scope min 0.694, OOS max 0.559)
#
# We set the threshold to 0.60 — within the gap, asymmetrically biased
# toward accepting (margin: 0.094 to in-scope min, 0.041 to OOS max).
# Reasoning: false rejection of legitimate queries is worse than false
# acceptance (the LLM is a backstop for false acceptance; there is no
# backstop for false rejection).
#
# Recalibrate when:
#  (a) The remaining ~1300 chunks (judgments) get embedded — more
#      diverse content may shift the OOS distribution.
#  (b) The Batch 8 eval set is run — 60 known-good queries will tell
#      us whether 0.60 produces any false rejections.
#
# Prior value 0.45 was a conservative guess against the 7-chunk test
# fixture from Chunk 3.2; it generalized poorly to the real index.
SCOPE_REJECTION_SIMILARITY_THRESHOLD: float = 0.60


# ---------------------------------------------------------------------------
# Out-of-scope rejection helper suggestions.
# ---------------------------------------------------------------------------
# When we reject a query as out-of-scope, the response includes suggested
# in-scope example questions. These are surfaced to the frontend's
# ScopeRejectionPanel (see AGENT-frontend.md §12.2). Keeping them as
# constants (not pulled from a config file) means they stay in the
# Python code that owns the rejection logic — one place to edit.
OUT_OF_SCOPE_EXAMPLE_QUERIES: tuple[str, ...] = (
    "What is the difference between robbery and dacoity?",
    "What does Section 397 IPC require to apply?",
    "When does theft become robbery under BNS Section 309?",
)