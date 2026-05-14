# Contributing

Thank you for considering a contribution. This is a portfolio project, but real contributions — bug fixes, eval set expansions, documentation improvements — are welcome.

## Project Scope

This project is intentionally narrow: **Indian robbery law** under BNS §§309-311 and IPC §§390-402. Contributions that broaden the scope (other offences, other jurisdictions, multi-turn conversation, etc.) will be politely declined. The narrow scope is a feature, not a limitation — it lets the system go deep where breadth-first systems can't.

Out of scope, explicit non-goals: see [`design.md` §14](./design.md#14-out-of-scope-explicit-non-goals).

## Before You Start

1. Read [`design.md`](./design.md) — the authoritative spec for what we're building and how.
2. Read the relevant agent guide:
   - [`AGENT.md`](./AGENT.md) for Python (backend, ingestion, eval)
   - [`AGENT-frontend.md`](./AGENT-frontend.md) for React/TypeScript
3. Pick an issue tagged `good-first-issue` or open one to discuss your idea before writing code.

## Setup

### Prerequisites

- Python 3.11+
- Node.js 20 LTS
- pnpm: `npm install -g pnpm`
- A Gemini API key (free tier sufficient): https://aistudio.google.com

### First-time setup

```bash
git clone https://github.com/<your-username>/indian-robbery-rag.git
cd indian-robbery-rag

# Backend
cd backend
python -m venv .venv
source .venv/bin/activate   # On Windows: .venv\Scripts\activate
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env        # add your GEMINI_API_KEY

# Frontend
cd ../frontend
cp .env.example .env
pnpm install
```

The system runs end-to-end on a local machine with no Azure access — see [`AGENT.md` §2](./AGENT.md#2-local-first-development) for the local-vs-cloud adapter design.

## The Pre-Commit Gate

Before opening a PR, all of the following must pass locally:

```bash
# Backend
cd backend
make check   # runs: ruff check . && ruff format --check . && mypy . && pytest -x

# Frontend
cd frontend
pnpm check   # runs: tsc --noEmit && eslint . && prettier --check . && vitest run
```

CI enforces the same gate. A red CI blocks merge.

## Coding Conventions — Short Version

Full conventions live in `AGENT.md` and `AGENT-frontend.md`. The short version:

- **Names over comments.** Function and variable names should make comments unnecessary.
- **Why-comments only.** Comments explain reasoning that names can't carry. Never restate what the code does.
- **Types are mandatory.** `mypy --strict` for Python, `tsc --strict` for TypeScript. No `any` without justification.
- **Local first.** Every external dependency has a local adapter behind a Protocol/interface. No direct cloud SDK imports in business logic.
- **Tests are required** for new logic. Use the DI container to inject local adapters; avoid mocks where possible.

## Commit Messages

Use conventional, meaningful commit messages. Examples:

- `feat(rag): add cross-encoder re-ranker after hybrid retrieval`
- `fix(cache): handle Cosmos retry-after on burst writes`
- `docs(readme): document local SQLite adapter setup`
- `test(scope): add eval cases for §392 vs §309 BNS mapping`

Avoid `fix`, `wip`, `update`, `stuff`. Squash before merging.

## PR Checklist

Before opening a PR:

- [ ] All tests pass locally (`make check` / `pnpm check`)
- [ ] New logic has tests
- [ ] Public APIs have one-line docstrings (Python) or are self-explanatory (TypeScript)
- [ ] No `print()` (Python) or `console.log()` (TS) left in code
- [ ] No hardcoded secrets, paths, or magic numbers
- [ ] If you changed `data/`, you ran `python scripts/normalize_filenames.py --apply` and the verifier passes
- [ ] If you changed `sources.yaml`, you re-ran the relevance classifier on affected entries
- [ ] If you changed the corpus, you bumped `CORPUS_VERSION`

## Reporting Bugs

Open an issue with:

- What you expected
- What happened
- A minimal reproduction (query text, environment, version)
- Logs if available (with secrets/PII redacted)

## Reporting Wrong Legal Outputs

If the system returns an incorrect or misleading legal answer, that's a high-priority bug. Please open an issue with:

- The exact query
- The response (including citations)
- What's wrong (incorrect citation, wrong doctrine, missing nuance)
- A reference to the correct position (case citation or section reference)

Bonus credit if you're a law student or junior advocate and willing to be credited as a reviewer in the README.

## Eval Set Contributions

The eval set in `eval/robbery_questions.jsonl` is the single highest-impact place to contribute. To add a question:

1. Fork the repo
2. Add an entry following the schema in `eval/schema.md`
3. Verify your `expected_sections` and `expected_cases` against Indian Kanoon yourself
4. Note any spot-check reviewer in `reviewed_by`
5. Open a PR; CI runs the eval against the new question and reports results

Eval contributions from law students and practising advocates are especially welcome.

## Code of Conduct

Be respectful. Disagree with ideas, not people. No personal attacks, no harassment, no discrimination.

If something feels off, open an issue or contact the maintainers privately.

## License

By contributing, you agree your contribution is licensed under the MIT License (see [`LICENSE`](./LICENSE)).
