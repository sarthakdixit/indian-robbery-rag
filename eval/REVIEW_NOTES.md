# Eval Set Review Notes

This file is the audit trail of human review of the eval set. Per `design.md` EV-5, at least 10-15 questions should be spot-checked by a law student or junior advocate before the eval results in the README are considered defensible.

This is a **portfolio integrity document**. Recruiters and reviewers should be able to read this and understand: who reviewed the eval set, what they checked, and what they corrected.

## Status

- **v1 (initial, unreviewed):** 60 questions. Author: project owner. Reviewed: nobody yet. All `reviewed_by` fields in `robbery_questions.jsonl` are `null`.
- **v1.1 (target):** at least 15 of the 60 questions reviewed by an external legal reviewer, with any corrections incorporated and the reviewer credited below.

## Why human review matters

Three failure modes the author cannot reliably catch alone:

1. **Wrong "ground truth"** — claiming a case stands for a proposition it doesn't actually hold for. A law student catches this in 30 seconds; an LLM-author may not.
2. **Stale citations** — case names that look right but have a typo, wrong year, or were overruled. Verified citations are the bedrock of the eval set's credibility.
3. **Doctrinal nuance** — Indian robbery doctrine has subtleties (e.g., "in order to commit theft" is not the same as "during theft"; vicarious liability under §397 vs §34). An author drafting 60 questions in a few hours will phrase some questions ambiguously enough that two correct answers are possible.

## Reviewer profile

Ideal reviewer:

- Final-year law student (LL.B. or LL.M.) or junior advocate (0-3 years)
- Some exposure to criminal law (paper on IPC/CrPC/BNS in coursework, or assisted a senior on a robbery matter)
- Comfortable reading SCC / AIR citations and cross-referencing on Indian Kanoon
- No financial relationship with the project (so the review carries weight)

**What to ask the reviewer to do:**

1. Pick any 15 of the 60 questions across all four categories (3-4 per category)
2. For each, verify:
   - Question is unambiguous (one correct answer, not multiple)
   - `expected_sections` correctly identifies the controlling provision(s)
   - `expected_cases` (where listed) are real cases that hold what the answer implies
   - `expected_answer_themes` cover the substantive points a good answer must mention
   - For `out_of_scope` items, the rationale in `reviewer_notes` is sound
3. Flag any question that needs amendment, deletion, or "needs more thought"
4. Suggest up to 5 questions that should be added (especially edge cases the author missed)

**Compensation:** A meaningful acknowledgment in the project README is the entire compensation. If the reviewer prefers to be uncredited or pseudonymous, note that in the entry below.

## How to record a review

When a reviewer completes their pass, add an entry to the table below and update the `reviewed_by` / `reviewer_notes` fields in `robbery_questions.jsonl` for each question they checked. The convention for `reviewed_by` is the same identifier used in the table.

`reviewed_by` values can be:

- A first name + last-initial: `"asha-k"`
- A handle: `"goldfish42"` (if pseudonymous)
- `"author"` if the author re-reviewed after time away

## Reviewer log

| Reviewer ID  | Real name | Affiliation | Date | Questions reviewed | Major findings |
| ------------ | --------- | ----------- | ---- | ------------------ | -------------- |
| _(none yet)_ |           |             |      |                    |                |

## Worked example of a completed review entry

(This is what a future row should look like — provided here as a template, not as a real review.)

```
| Reviewer ID | Real name      | Affiliation                | Date         | Questions reviewed | Major findings |
|-------------|----------------|----------------------------|--------------|--------------------|----------------|
| asha-k      | Asha Krishnan  | NLSIU Bangalore, LL.B. III | 2026-06-15   | 16                 | (1) ing_005 — confirmed Phool Kumar and Ashfaq cover the doctrine, but Ashfaq is also a good citation for the "co-accused not vicariously liable" line — added to ing_006. (2) sen_007 — corrected expected punishment for §396: it's death OR imprisonment for life, not death + IL. (3) map_008 — flagged that BNS dacoity-with-murder maps to §310(3) specifically, not generic §310. Updated. (4) Added two suggested questions on §394 (hurt in committing robbery) and §398 (use of weapon during attempted dacoity) — will incorporate in v1.2. |
```

## After review: amendment process

When the reviewer flags corrections:

1. Update the affected questions in `robbery_questions.jsonl`
2. Set their `reviewed_by` field to the reviewer's ID
3. Add the reviewer's note (or a summarized version) to the `reviewer_notes` field
4. Append a row to the reviewer log table above
5. Bump the eval set version (informally, in this file's "Status" section)
6. Commit with message: `eval: incorporate review by <reviewer_id>`

If the reviewer disagrees with the author on a question and no consensus emerges, leave the question as-is, but note the disagreement in this file. A genuine doctrinal disagreement is itself a finding — it tells future users where the law is unsettled.

## Re-reviews

The eval set should be re-reviewed:

- When the underlying corpus changes meaningfully (e.g., a new landmark SC case lands)
- When the system's eval-harness results show systematic failures in one category
- Annually, even if nothing has changed, just to catch staleness

Each re-review gets a new row in the log table. The history is the audit trail.

## Acknowledgments

(To be populated as reviews land. Suggested wording for the README acknowledgments section:)

> _"The eval set was reviewed by Asha Krishnan (NLSIU Bangalore) in June 2026. Any errors that remain are mine, not hers."_

This single sentence in the README is worth more than fifty more eval questions written by the author alone.
