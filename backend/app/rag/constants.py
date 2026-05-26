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
# Picking the right value requires empirical calibration: a relevant
# robbery question against a normalized gemini-embedding-001 index should
# score 0.6-0.8 on top-1; an off-topic question should score 0.2-0.4.
# We default to 0.45 to favour false negatives (over-accept) over false
# positives (over-reject) until we have an eval set. The 0.55 figure in
# design.md is a guess from the original planning document; this lower
# value is more conservative.
#
# Override in Settings for environment-specific tuning.
SCOPE_REJECTION_SIMILARITY_THRESHOLD: float = 0.45


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