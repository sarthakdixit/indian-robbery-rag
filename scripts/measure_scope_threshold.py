"""Empirical scope-threshold diagnostic.

Measures the top_vector_similarity score that the retrieval layer
produces for a hand-curated set of known-in-scope and known-OOS
queries. Output is a score distribution plus a recommended threshold.

Cost: 1 embedding API call per query (~20 calls total). No generation
calls. Fits comfortably inside the daily embedding quota.

Run with:
    python3 scripts/measure_scope_threshold.py

The script does NOT modify any source files. It only prints a
recommendation; threshold updates are a manual edit to
backend/app/rag/constants.py.
"""

from __future__ import annotations

import asyncio
import statistics
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))

from backend.app.config import get_settings  # noqa: E402
from backend.app.container import Container  # noqa: E402


# ---------------------------------------------------------------------
# Query corpus
# ---------------------------------------------------------------------
# Hand-curated, diverse. Avoiding any borderline cases — these should
# be obvious to a human (and to the retrieval system).

IN_SCOPE_QUERIES: list[str] = [
    "What is robbery under BNS?",
    "What is the punishment for robbery?",
    "How does robbery differ from theft?",
    "What is dacoity?",
    "Is robbery a cognizable offence?",
    "What is the difference between robbery and extortion?",
    "Robbery under section 392 of IPC",
    "Voluntarily causing hurt during robbery",
    "Attempt to commit robbery punishment",
    "Robbery on the highway between sunset and sunrise",
    "What does BNS section 309 say?",
    "Mapping of IPC 392 to BNS",
]

OUT_OF_SCOPE_QUERIES: list[str] = [
    "How do I bake chocolate chip cookies?",
    "What is the population of Tokyo?",
    "How do I configure my home Wi-Fi router?",
    "What are the symptoms of vitamin D deficiency?",
    "How do I write a Python web scraper?",
    "What is the best way to learn guitar?",
    "What is the airspeed velocity of an unladen swallow?",
    "How do I file my income tax in Australia?",
    "What is photosynthesis?",
    "How does the stock market work?",
    "What is the recipe for chicken biryani?",
    "How do I train for a marathon?",
]


# ---------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------

async def score_query(retriever, query: str) -> tuple[float, str]:
    """Return (top_vector_similarity, top_chunk_id) for a query.

    We bypass `Retriever.retrieve` because that applies the scope
    threshold internally. Instead we replicate the relevant logic —
    embed, vector search top-1, return the score. This isolates the
    measurement from the threshold we're trying to tune.
    """
    qe = await retriever._embeddings.embed_query(query)
    vector_hits = await retriever._vector_store.search(qe, top_k=5)
    if not vector_hits:
        return (0.0, "<no vector hits>")
    top = vector_hits[0]
    return (top.score, top.chunk_id)


async def main() -> None:
    settings = get_settings()
    print(f"Settings: environment={settings.environment}, "
          f"chroma_db_dir={settings.chroma_db_dir}")
    print(f"Embedding model: {settings.gemini_embedding_model}")
    print()

    # Container's config provider auto-reads via get_settings(). No
    # explicit wiring needed; the providers we touch (embeddings_client,
    # vector_store, bm25) all resolve transitively.
    container = Container()
    retriever = container.retriever()

    # --- Score every query --------------------------------------------
    print("Scoring in-scope queries...")
    in_scope_scores: list[tuple[str, float, str]] = []
    for q in IN_SCOPE_QUERIES:
        score, chunk_id = await score_query(retriever, q)
        in_scope_scores.append((q, score, chunk_id))
        print(f"  {score:.4f}  {chunk_id[:30]:30}  {q}")
    print()

    print("Scoring out-of-scope queries...")
    oos_scores: list[tuple[str, float, str]] = []
    for q in OUT_OF_SCOPE_QUERIES:
        score, chunk_id = await score_query(retriever, q)
        oos_scores.append((q, score, chunk_id))
        print(f"  {score:.4f}  {chunk_id[:30]:30}  {q}")
    print()

    # --- Aggregate ----------------------------------------------------
    in_vals = sorted(s for _, s, _ in in_scope_scores)
    oos_vals = sorted(s for _, s, _ in oos_scores)

    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"In-scope   ({len(in_vals)} queries):")
    print(f"  min:    {min(in_vals):.4f}")
    print(f"  median: {statistics.median(in_vals):.4f}")
    print(f"  max:    {max(in_vals):.4f}")
    print()
    print(f"Out-of-scope ({len(oos_vals)} queries):")
    print(f"  min:    {min(oos_vals):.4f}")
    print(f"  median: {statistics.median(oos_vals):.4f}")
    print(f"  max:    {max(oos_vals):.4f}")
    print()

    in_min = min(in_vals)
    oos_max = max(oos_vals)
    print(f"Boundary: in-scope min = {in_min:.4f}, OOS max = {oos_max:.4f}")

    if in_min > oos_max:
        midpoint = (in_min + oos_max) / 2
        gap = in_min - oos_max
        print(f"Clean separation. Gap = {gap:.4f}")
        print(f"Recommended threshold: {midpoint:.4f}")
        print()
        print("At this threshold:")
        print(f"  - All {len(in_vals)} in-scope queries pass (lowest is {in_min:.4f})")
        print(f"  - All {len(oos_vals)} OOS queries are rejected (highest is {oos_max:.4f})")
    else:
        overlap = oos_max - in_min
        print(f"OVERLAP — in-scope and OOS sets overlap by {overlap:.4f}")
        print()
        print("Pick threshold based on which failure mode you prefer:")
        print(f"  - Threshold = OOS max + epsilon ({oos_max + 0.01:.4f}): ")
        print(f"      rejects all OOS but loses "
              f"{sum(1 for v in in_vals if v < oos_max + 0.01)} legitimate queries")
        print(f"  - Threshold = in-scope min - epsilon ({in_min - 0.01:.4f}): ")
        print(f"      accepts all in-scope but lets "
              f"{sum(1 for v in oos_vals if v > in_min - 0.01)} OOS queries through")
        print()
        print("Overlapping queries (potential mis-routing):")
        for q, s, chunk_id in oos_scores:
            if s > in_min:
                print(f"  OOS scoring HIGH:   {s:.4f}  {q}  -> {chunk_id[:40]}")
        for q, s, chunk_id in in_scope_scores:
            if s < oos_max:
                print(f"  in-scope scoring LOW: {s:.4f}  {q}  -> {chunk_id[:40]}")


if __name__ == "__main__":
    asyncio.run(main())