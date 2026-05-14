# eval/

The evaluation harness — the single most important folder for proving the RAG system works.

## Purpose

This is what separates a portfolio RAG project from a tutorial clone. The eval set is a held-out collection of 50-100 robbery questions with verified ground-truth answers. The harness runs them through the full pipeline and reports:

- **Retrieval@5** — did the right BNS/IPC section or case appear in the top-5 retrieved chunks?
- **Citation accuracy** — did the generated answer cite real sources from the retrieved set (no hallucinated citations)?
- **Out-of-scope rejection rate** — did the system correctly reject queries that aren't about robbery?
- **Latency** — p50, p95, p99 end-to-end
- **Per-category breakdown** — performance broken down by question type

These numbers go directly into the README and are the headline of every interview conversation about this project.

## Layout

```
eval/
├── robbery_questions.jsonl         The eval set itself
├── schema.md                       Documentation of the JSONL fields
├── categories.md                   Description of the four question categories
├── REVIEW_NOTES.md                 Audit trail of human spot-checks
├── run_eval.py                     Runs all questions, computes metrics
├── metrics.py                      Pure-function metrics computations
├── llm_judge.py                    Secondary LLM-as-judge grading
├── report_template.md              Markdown template for results
└── results/
    ├── baseline.json               Latest run output
    ├── failure_analysis.md         Diagnosis of 5-10 underperforming questions
    └── category_breakdown.md       Per-category metrics narrative
```

## Status

Empty scaffolding. Files arrive over Batches 1 and 8:

- **Batch 1** — `robbery_questions.jsonl`, `schema.md`, `categories.md`, `REVIEW_NOTES.md`
- **Batch 8** — `run_eval.py`, `metrics.py`, `llm_judge.py`, `report_template.md`, and the populated `results/`

## The Four Question Categories

From [`../design.md` EV-2](../design.md#5-evaluation-requirements):

1. **Ingredient analysis** (~15 questions) — Theft vs robbery vs dacoity distinctions; "force or fear", "in order to commit theft", "5+ persons"
2. **Sentencing and bail jurisprudence** (~15 questions) — §392, §397 punishment ranges; aggravating/mitigating factors; bail considerations
3. **IPC-to-BNS mapping** (~15 questions) — How old IPC sections (§390-402) map to new BNS sections (§§303-313), especially for transition cases
4. **Out-of-scope rejection** (~15 questions) — Questions about murder, theft alone, dowry death, etc., that the system MUST refuse

Each category is curated to surface a specific class of capability or failure mode.

## Eval Set Format

`robbery_questions.jsonl` — one question per line:

```json
{
  "id": "rob_001",
  "category": "ingredient",
  "question": "What is the difference between theft and robbery under Indian law?",
  "expected_sections": ["BNS-309", "BNS-303", "IPC-390", "IPC-378"],
  "expected_cases": ["Venu @ Venugopal v. State of Karnataka"],
  "expected_answer_themes": [
    "force or fear",
    "in order to commit theft",
    "aggravated form of theft"
  ],
  "expected_to_reject": false,
  "reviewed_by": "verified",
  "reviewer_notes": "Foundational distinction. Venu case is the modern restatement."
}
```

For out-of-scope questions, `expected_to_reject: true` and the other fields are nulls.

Full schema documented in `schema.md` (Batch 1).

## Human Review

Per [`../design.md` EV-5](../design.md#5-evaluation-requirements), at least 10-15 questions must be spot-checked by a law student or junior advocate. The reviewer's name and credentials go in `REVIEW_NOTES.md` and the project README. This is the single cheapest insurance against interview disaster (a wrong "ground truth" answer that a reviewer catches).

## Running the Eval

```bash
# After Batch 8 lands:
cd eval
python run_eval.py --output results/baseline.json
```

This:

1. Loads every question from `robbery_questions.jsonl`
2. Submits each to the local backend
3. Records retrieval, citations, answer, latency
4. Computes metrics per category
5. Runs LLM-as-judge for an answer quality score
6. Writes a markdown report from `report_template.md`

Total runtime: ~10-15 minutes for 50-100 questions (dominated by Gemini latency, not anything we control).

## Contributing Questions

The eval set is the single highest-impact place to contribute. See [`../CONTRIBUTING.md`](../CONTRIBUTING.md#eval-set-contributions) for the workflow.

Reviewers from the legal community are especially welcome — being credited as a reviewer is a meaningful signal of project rigor.
