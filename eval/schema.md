# Eval Set Schema

The eval set lives in `robbery_questions.jsonl`. One JSON object per line. Every line must conform to the schema below.

## Fields

| Field                    | Type           | Required | Notes                                                                                                                                                                           |
| ------------------------ | -------------- | -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `id`                     | string         | yes      | Unique identifier. Convention: `<category-prefix>_<3-digit>`. Prefixes: `ing` (ingredient), `sen` (sentencing_bail), `map` (ipc_bns_mapping), `oos` (out_of_scope).             |
| `category`               | string         | yes      | One of: `ingredient`, `sentencing_bail`, `ipc_bns_mapping`, `out_of_scope`. See `categories.md`.                                                                                |
| `question`               | string         | yes      | The natural-language query as a user would type it. Realistic phrasing, not academic formalism.                                                                                 |
| `expected_sections`      | string[]       | yes      | Statutory sections the answer must cite. Format: `"BNS-309"`, `"IPC-390"`, `"BNSS-482"`, `"CrPC-438"`. Empty list for `out_of_scope` questions.                                 |
| `expected_cases`         | string[]       | yes      | Case names the answer should cite. Must match a case in `sources.yaml`. Empty list for `out_of_scope` questions; may be empty for in-scope if the question is purely statutory. |
| `expected_answer_themes` | string[]       | yes      | Short phrases (2-8 words each) capturing the key concepts the answer must mention. Used by the LLM-as-judge for grading semantic correctness. Empty for `out_of_scope`.         |
| `expected_to_reject`     | boolean        | yes      | `true` if the system MUST decline to answer (out-of-scope, harmful, prompt-injection). `false` for substantive robbery questions.                                               |
| `reviewed_by`            | string \| null | yes      | Identifier of the human reviewer if spot-checked. `null` initially. See `REVIEW_NOTES.md` for the audit trail.                                                                  |
| `reviewer_notes`         | string \| null | yes      | Short note from the reviewer or, for `out_of_scope` items, a one-line rationale for why this question is out of scope. `null` if not reviewed and not otherwise annotated.      |

## Validation rules enforced by `eval/run_eval.py` (Batch 8)

- Every line must parse as JSON and have all required fields
- `id` must be unique across the file
- `category` must be one of the four allowed values
- If `expected_to_reject` is `true`, then `expected_sections`, `expected_cases`, and `expected_answer_themes` MUST be empty lists. (You're saying the system shouldn't answer — there's nothing to grade against.)
- If `expected_to_reject` is `false`, then `expected_sections` MUST have at least one entry. (Every substantive question must be groundable to a statutory provision.)
- Citation strings in `expected_cases` must exactly match `case_name` values in `sources.yaml`. Mis-named citations are caught at eval time and reported as ground-truth errors.

## How the eval harness uses each field

The eval harness (`run_eval.py`, lands in Batch 8) submits each question to the running backend and grades the response. The grading logic for each field:

- **`expected_sections`** → checked against retrieved chunks. Score = fraction of expected sections present in the top-5 retrieved chunks. Reported as **retrieval@5 by section**.
- **`expected_cases`** → checked against citations in the generated answer. Score = fraction of expected cases actually cited (and zero hallucinated citations). Reported as **citation precision and recall**.
- **`expected_answer_themes`** → checked by an LLM-as-judge ("does the answer substantively cover these themes?"). Reported as **theme coverage**. This is the softest metric — humans should spot-check the judge's calls.
- **`expected_to_reject`** → checked against the backend's response type. Score = was the rejection correct (true positive) or did the system answer something it shouldn't have (false negative)? Reported as **rejection accuracy**.

## Schema versioning

The schema may evolve. If we add a field, existing rows without it default to `null` (or `false` / `[]` as appropriate). If we change semantics of an existing field, bump the schema version in `categories.md` and re-review the eval set.

Current schema version: **1**.
