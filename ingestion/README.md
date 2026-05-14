# ingestion/

Offline scripts that turn the raw corpus in [`../data/`](../data/) into a queryable ChromaDB index.

## Purpose

This is **batch work**, not a service. Scripts under `ingestion/` run once on a developer laptop, produce static artifacts (a ChromaDB folder, a BM25 pickle), and exit. The backend never imports from here at runtime.

The pipeline has four stages:

1. **Collect & verify** — confirm the raw corpus is present at expected paths with the correct filename conventions (per [`../design.md` CORP-5](../design.md#8-data--corpus-requirements))
2. **Classify** — run every judgment through a Gemini-based relevance classifier; mark off-topic cases as rejected so they don't pollute the index
3. **Normalize** — extract clean text from Indian Kanoon HTML (BeautifulSoup) and indiacode.nic.in PDFs (pdfplumber); preserve paragraph numbers and section metadata
4. **Chunk** — split normalized text into ~300-500 token chunks with full metadata (case name, section, citation, year, court, outcome, source URLs)

A separate downstream stage (Batch 2) embeds the chunks via Gemini and builds the ChromaDB index. That lives under `ingestion/embed/` and `ingestion/index/`.

## Layout (anticipated)

```
ingestion/
├── collect/
│   ├── verify_corpus.py            Asserts data/ matches sources.yaml, computes SHA-256
│   └── README.md                   Methodology + download playbook
├── classify/
│   ├── relevance_classifier.py     Single-judgment Gemini classifier
│   ├── run_classifier.py           Orchestrator, writes results back to sources.yaml
│   ├── prompts.py                  System + user prompt templates
│   └── README.md
├── normalize/
│   ├── clean_html.py               BeautifulSoup extractor for Indian Kanoon HTML
│   ├── parse_acts_pdf.py           pdfplumber-based statute parser
│   ├── parse_judgments.py
│   └── schema.py                   Pydantic models for normalized output
├── chunk/
│   ├── chunker.py                  Paragraph-aware splitter with token cap
│   ├── metadata.py
│   └── run_chunking.py             Writes chunks.jsonl
├── embed/                          Batch 2 — Gemini embeddings
├── index/                          Batch 2 — ChromaDB + BM25 builder
├── run_ingestion.py                Top-level orchestrator (Batch 2)
├── config.py
├── requirements.txt
└── Makefile                        `make ingest` runs the whole pipeline
```

## Status

Empty scaffolding. Files arrive over Batches 1-2:

- **Batch 1** — Manifest, verifier, relevance classifier, normalizer, chunker
- **Batch 2** — Embedding client, ChromaDB index builder, top-level orchestrator

## The Local-Only Rule

These scripts run **only** during ingestion, **only** on a developer machine, and **only** before deployment. They produce build artifacts (`chroma_db/`, `bm25.pkl`) which then get baked into the backend Docker image.

This means [`../AGENT.md`](../AGENT.md) relaxes some rules inside `ingestion/`:

- Sync I/O is allowed (these are batch scripts; async is unnecessary overhead)
- The Gemini sync SDK (`generate_content`, not `generate_content_async`) is the correct choice here
- No dependency injection container needed — these scripts are top-down scripts, not services
- No FastAPI, no HTTP, no Cosmos DB adapters

What still applies: `mypy --strict`, type hints everywhere, no `print()` (use `structlog`), constants in `constants.py` modules, Pydantic for cross-module data.

## Running the Pipeline

```bash
# After Batch 2 lands:
cd ingestion
pip install -r requirements.txt
make ingest
```

This:

1. Verifies the corpus in `../data/`
2. Runs the relevance classifier (skipped if `sources.yaml` already has scores)
3. Normalizes and chunks
4. Embeds via Gemini
5. Writes the ChromaDB index to `../chroma_db/` and BM25 to `../bm25.pkl`

Re-running is idempotent: cached embeddings are re-used, and only chunks whose `corpus_version` differs get re-embedded.

## Corpus Refresh

When you add or remove cases:

1. Edit `data/` (add a new numbered folder, or update sources.yaml)
2. Run `python scripts/normalize_filenames.py --apply` if needed
3. Bump `CORPUS_VERSION` in `backend/app/constants.py`
4. Run `make ingest`
5. Commit `data/`, `sources.yaml`, and the bumped `CORPUS_VERSION`

The built artifacts (`chroma_db/`, `bm25.pkl`) are gitignored — they're rebuilt by the Docker image during backend deployment.
