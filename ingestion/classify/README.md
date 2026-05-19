# ingestion/classify/

Gemini-based relevance classifier for the corpus. Filters bulk-downloaded judgments down to those substantively about robbery.

## What lives here

- **`prompts.py`** — System and user prompt templates. Constants only; no logic.
- **`relevance_classifier.py`** — Single-judgment classifier. Reads an HTML file, extracts a brief excerpt, sends a request to Gemini with a Pydantic `response_schema`, returns a validated `ClassifierVerdict`.
- **`run_classifier.py`** — Orchestrator. Iterates pending judgments in `sources.yaml`, calls the classifier on each, writes results back to the manifest. Idempotent, rate-limit-aware, resumable.

## When to run this

After Chunk 1.1's `verify_corpus.py` passes cleanly and you have judgments listed in `sources.yaml` with `relevance_classifier_status: pending`. The classifier never re-touches already-scored entries unless `--force` is passed.

## How to run

```bash
export GEMINI_API_KEY=...    # free tier from https://aistudio.google.com
python ingestion/classify/run_classifier.py
```

Other flags:

- `--dry-run` — show what would be classified without calling Gemini
- `--force` — re-classify entries that already have a score
- `--only 01,03,07` — classify just these folders
- `--verbose` — debug logging

Exit code 0 means clean, 1 means at least one classification failure, 2 means configuration error.

For a corpus of 50 judgments at ~4.5s between calls, expect ~4 minutes runtime. Gemini's free tier allows 15 requests per minute; we stay well under that ceiling.

## How classification works

For each pending judgment:

1. **Extract excerpt** (~3000 chars) from the HTML file using BeautifulSoup. Strips scripts, styles, nav/header/footer. Returns the cleaned text of the judgment body.
2. **Build prompt** with case name, citation, court, year, primary section claimed in the manifest, and the excerpt.
3. **Call Gemini** with `response_schema=ClassifierVerdict`. The SDK constrains generation to match the Pydantic schema, so the response is guaranteed valid JSON.
4. **Validate** the response against `ClassifierVerdict`. Reject anything that doesn't pass.
5. **Derive status** from the score:
   - `score >= 0.6` → `approved`
   - `0.4 <= score < 0.6` → `needs-review` (human eyeballs required)
   - `score < 0.4` → `rejected`
6. **Write back** to `sources.yaml`: `relevance_classifier_status`, `relevance_score`, `classifier_reasoning`.

If the classifier itself fails (Gemini timeout, malformed response, HTML missing), the entry becomes `needs-review` with the error captured in `manual_review_notes`. The run continues.

## Why a Pydantic response schema

The new `google-genai` SDK accepts a `response_schema=ClassifierVerdict` argument that constrains the model's generation to produce JSON matching the schema. This is materially stronger than just asking for JSON in the prompt — invalid responses become a class of error the SDK eliminates rather than us catching at parse time. We still validate with Pydantic on receipt as belt-and-suspenders.

## Prompt design rationale

The system prompt (`prompts.py`) is explicit about what counts as "substantively about robbery" and what does NOT. The exclusion list matters as much as the inclusion list — judgments mentioning robbery in passing (prior record, FIR-only mention, S.27 Evidence Act discussion without robbery-specific doctrine) should score low. Without explicit exclusions, the classifier is too permissive.

Scoring guidance is bucketed (0.9-1.0 landmark, 0.7-0.9 central, 0.5-0.7 partial, 0.3-0.5 marginal, 0.0-0.3 off-topic). Buckets make the model's intent legible in the score, not just the binary `is_relevant` field.

The prompt is a module-level constant — versioned with the code, not buried in a string inside a function. When tuning, change `prompts.py` and re-run with `--force` to see the score deltas.

## Threshold tuning

The boundaries (0.4 and 0.6) are starting values. Tune them empirically using the eval set in `eval/` (Batch 1.5) and the relevance check itself:

- If too many off-topic cases get `approved`, raise the upper threshold
- If too many genuinely-relevant cases land in `needs-review`, lower the upper threshold
- The `needs-review` band should be small but non-empty — it's where the classifier is uncertain and a human should look

## Cost

Free, in practice. The Gemini 1.5 Flash free tier allows 1500 requests per day. 50 judgments is 50 requests. Even re-running with `--force` ten times costs nothing.

If you exceed the free tier (you won't for this project), Gemini 1.5 Flash is roughly ₹0.01-0.05 per classification at portfolio token volumes.

## When the classifier disagrees with you

The classifier is a filter, not an oracle. If a case you believe is important gets `rejected`, you have three options:

1. **Trust the classifier.** Maybe the case isn't actually about robbery in the doctrinal sense — recheck against the system prompt's criteria.
2. **Manually override.** Edit `sources.yaml` to set `relevance_classifier_status: approved` and add a note in `manual_review_notes` explaining the override.
3. **Improve the prompt.** If the classifier is systematically missing a category (e.g., bail jurisprudence specifically), edit `prompts.py` and re-run with `--force`. Document the change in your commit message.

The `manual_review_notes` field exists exactly for case (2) — the audit trail of human disagreement with the classifier. Don't be afraid to use it.

## Troubleshooting

**`Gemini call failed: APIError`** — Check that `GEMINI_API_KEY` is correct and you haven't hit the daily 1500-request limit. The orchestrator sleeps 4.5s between calls to respect the per-minute limit.

**`excerpt too short`** — The HTML for that case failed to parse usefully. Open the HTML manually; it's probably a 404 page Indian Kanoon served when you misclicked, or a page where the judgment body uses a different markup structure than expected. Re-download and try again.

**`Gemini response did not match expected JSON schema`** — Rare with `response_schema` enabled. If it happens, log the raw response and consider adjusting the prompt.

**Many entries flagged `needs-review`** — Either your threshold band is too wide (consider tightening), or your corpus is genuinely marginal and you should consider stricter manual filtering before the classifier runs.

## What this chunk does NOT do

- No HTML normalization for the _full_ corpus — that's the chunker in Chunk 1.3. The excerpt extracted here is a lightweight reading for classification only.
- No re-ranking or quality scoring beyond relevance — the chunker handles structural quality.
- No batching of Gemini calls — one at a time, with a sleep between. Simpler, easier to resume, fine at our scale.
- No async — see AGENT.md §7.2 (ingestion is sync).
