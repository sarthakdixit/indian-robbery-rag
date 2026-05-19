# Embedding pipeline

Generates Gemini embeddings for the chunks produced by `ingestion/chunk/`
and writes them to `ingestion/data/embeddings.jsonl`. The embeddings are
later loaded into ChromaDB by `ingestion/index/`.

## What this module does

```
ingestion/data/chunks.jsonl    -->  embed_chunks.py  -->  ingestion/data/embeddings.jsonl
                                          |                       (chunk_id -> 768-dim vector)
                                          v
                              ingestion/data/embedding_cache.sqlite
                                  (resumable cache; survives quota stops)
```

## Files

- `gemini_client.py` — thin wrapper around `client.models.embed_content`
  from the `google-genai` SDK. Batches at 100 texts per API call (the
  hard cap). Returns one of three sentinel types per call:
  `EmbeddingsOk`, `QuotaExhausted`, `EmbeddingsError`. The caller decides
  what to do; the client never raises on quota or transient errors.
- `cache.py` — SQLite-backed `(text, model, task_type) -> embedding`
  cache. Vectors are stored as packed float32 BLOBs (3 KB per 768-dim
  vector). Atomic writes mean ctrl-C never corrupts state.
- `embed_chunks.py` — orchestrator. Reads chunks, consults cache,
  batches misses, writes successful batches back to cache before moving
  on, stops cleanly on quota.
- `README.md` — this file.

## The resume story

Gemini's free tier has tight daily quotas. For ~2100 chunks at 50 texts
per batched API call = ~42 batched calls. That's typically fine, but:

- If the daily quota is exhausted partway through, the script writes
  the partial output and exits with code 3.
- Every successful batch is persisted to the cache _before_ moving on.
- On the next run, the orchestrator computes cache hits vs misses and
  only calls Gemini for the misses.

Concretely: a run that gets through batches 1-20 of 42 before hitting
quota will, on the next day's run, log "cache: 1000 hits, 1100 misses" and
resume from batch 21.

## Why batch size 50 (not 100)

`gemini-embedding-001` caps a single batched request at **20,000 input
tokens** across all inputs (separate from the 250-inputs-per-request cap).
Our chunks average ~250 tokens but can spike up to ~1,300 tokens for the
occasional outlier (long act sections that didn't split cleanly on
paragraph breaks). At batch size 100, a worst-case batch could be 50,000+
tokens and the API would reject it.

Batch 50 keeps us comfortably under the 20K cap even in worst-case mixes,
at the cost of doubling the request count. For an offline ingestion run
that's already paced at one batch per second, this is fine.

## Why gemini-embedding-001, not text-embedding-004

`text-embedding-004` was the previous-generation model, deprecated by
Google on January 14, 2026. `gemini-embedding-001` is its successor:
trained on the Gemini base model, supports 8192-token inputs (vs 3000),
performs better on the MTEB benchmark.

The new model defaults to 3072-dimensional outputs but supports
Matryoshka Representation Learning truncation to 768 or 1536. We pick
768 to keep the persisted index small (4× smaller than 3072) and
ChromaDB queries fast, at minimal quality cost.

## Task types matter

Gemini's embedding model produces different vectors depending on the
declared `task_type`. For RAG, the right pairing is:

- **Ingestion**: `RETRIEVAL_DOCUMENT` (this script)
- **Query**: `RETRIEVAL_QUERY` (Batch 3 backend)

Mismatching these works — you get back vectors of the same shape — but
retrieval quality degrades because the model has been fine-tuned to make
the query-document direction asymmetric. The cache key includes the
task type, so vectors stored under one task type don't satisfy a lookup
under another.

## Why SQLite for the cache

Three reasons we didn't use a JSON-lines or pickle cache:

1. **O(1) lookups by hash.** We check the cache for every chunk on every
   run; a linear scan over 1,500 entries each time isn't fast enough.
2. **Atomic writes.** SQLite's WAL mode means a ctrl-C or kill -9 mid-
   run can't leave a torn write. A JSONL append could.
3. **No locking needed.** If we ever want to parallelize embedding
   across processes, SQLite handles concurrent reads automatically.

## Usage

```bash
# Dry run — show what would be embedded, no API calls
GEMINI_API_KEY=$KEY python ingestion/embed/embed_chunks.py --dry-run

# Full run
GEMINI_API_KEY=$KEY python ingestion/embed/embed_chunks.py

# Conservative — embed only the next 50 misses (useful when you want to
# leave quota headroom for the classifier or other Gemini calls today)
GEMINI_API_KEY=$KEY python ingestion/embed/embed_chunks.py --limit 50
```

Exit codes:

- `0` — all chunks embedded
- `1` — one or more permanent embedding failures (not quota)
- `2` — configuration error (missing API key, missing input, etc.)
- `3` — daily quota exhausted; re-run tomorrow to resume

## When to clear the cache

The cache is keyed on `(text, model, task_type)`. You should clear it if:

- You change the embedding model (e.g. text-embedding-004 → 005).
  The cache won't return stale vectors for the new model, but it'll
  keep the old vectors taking up disk space.
- You re-chunk the corpus with materially different chunk boundaries.
  Same text usually still hits the cache, but the chunk_ids will all
  be different, so the resulting `embeddings.jsonl` will refer to
  new ids.

To clear:

```bash
rm ingestion/data/embedding_cache.sqlite
```

Then re-run `embed_chunks.py` to repopulate. With the free-tier daily
quota, this can take several days, so don't clear lightly.
