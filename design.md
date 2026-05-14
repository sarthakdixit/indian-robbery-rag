# DESIGN: Indian Robbery Law RAG Assistant

> **Status:** Pre-build planning document. This is the authoritative source of truth for what we are building and how it will be assembled. Update this file when scope or sequencing changes — do not let code and design drift apart.

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Functional Requirements](#2-functional-requirements)
3. [Non-Functional Requirements](#3-non-functional-requirements)
4. [Abuse Protection](#4-abuse-protection-defense-in-depth)
5. [Evaluation Requirements](#5-evaluation-requirements)
6. [Repository & Documentation Requirements](#6-repository--documentation-requirements)
7. [Services & Tech Stack](#7-services--tech-stack)
8. [Data & Corpus Requirements](#8-data--corpus-requirements)
9. [Cosmos DB Schema](#9-cosmos-db-schema)
10. [System Architecture](#10-system-architecture)
11. [Build Methodology](#11-build-methodology)
12. [Batch & Chunk Plan](#12-batch--chunk-plan)
13. [Timeline & Milestones](#13-timeline--milestones)
14. [Out of Scope](#14-out-of-scope-explicit-non-goals)
15. [Cost Summary](#15-cost-summary)

---

## 1. Project Overview

**Domain:** Indian criminal law — robbery offences only (BNS Sections 309-311, mapped from IPC 390-402 for transition cases).

**Use case:** Single-turn legal research Q&A for law students, legal researchers, and curious users. Question in, answer with citations out.

**Purpose:** Portfolio project demonstrating production-grade RAG engineering on a constrained budget (~Rs 500/month).

**Target audience for the portfolio:** AI/ML engineering roles, legal-tech startups, Indian enterprises using Azure stack.

---

## 2. Functional Requirements

- **FR-1: Single-turn Q&A.** User submits one question, receives one answer with citations. No conversation history, no follow-up context.
- **FR-2: Footnote-style citations.** Every answer includes numbered references with expandable cards showing the full source chunk and metadata (act, section number, case name, citation, year).
- **FR-3: Scope enforcement.** System rejects out-of-scope questions via embedding similarity threshold *before* calling the LLM. Rejected queries do not count toward rate limits. Rejection UI shows 3 suggested example questions.
- **FR-4: Anonymous public access.** No login. No user accounts. Anyone with the URL can query.
- **FR-5: Rate limiting.** 5 queries per IP per 24-hour rolling window. Plus a global daily cap (e.g., 200 queries/day across all IPs) as a kill-switch.
- **FR-6: Two-layer caching.** Exact-match cache checked first. Semantic cache (embedding similarity, threshold ~0.92) as fallback. Cache invalidates on `corpus_version` bump.
- **FR-7: Pre-populated demo cache.** 4-5 example questions visible as clickable buttons on the landing page, with responses pre-cached at deploy time.
- **FR-8: Citation verification.** Every numbered citation in the LLM's output is validated against the retrieved chunk set before returning to the user. Invalid citations stripped or flagged.
- **FR-9: Disclaimer & legal framing.** Prominent top banner, one-time first-visit modal requiring "I understand" click, per-answer footer disclaimer. Includes BNS in-force date (July 1, 2024) and IPC applicability for older offences. Privacy note covering query logging.
- **FR-10: Analytics dashboard.** Password-protected `/admin` route showing queries per day, average and p95 latency, estimated cost-to-date, top 10 most-asked questions, recent queries table, retrieval hit rate, rejection rate, cache hit rate.
- **FR-11: Custom error states.** Specific UI for cold start, rate limit hit, scope rejection, and generic fallback.
- **FR-12: Terms of Use page.** Boilerplate covering no warranty, no liability, educational purpose, query logging policy.

---

## 3. Non-Functional Requirements

- **NFR-1: Cost.** Target Rs 500/month. Realistic estimate Rs 50-250/month.
- **NFR-2: Cold start.** Container Apps scale-to-zero accepted. First-request latency target: under 20 seconds with loading state visible within 500ms.
- **NFR-3: Warm response latency.** Target p95 under 4 seconds end-to-end.
- **NFR-4: Availability.** Best-effort. No SLA. Acceptable to be down during budget cap or LLM outages, provided users see a meaningful message.
- **NFR-5: Mobile responsive.** Frontend must work on mobile browsers.
- **NFR-6: Privacy.** Queries logged for analytics and abuse prevention. IP addresses stored as salted SHA-256 hashes, never raw. No personal information collected.
- **NFR-7: Reproducibility.** Anyone with the GitHub repo and an Azure subscription should be able to deploy the system end-to-end.

---

## 4. Abuse Protection (Defense in Depth)

- **AP-1: Cloudflare Turnstile.** Hard requirement. Invisible CAPTCHA on the query endpoint.
- **AP-2: Per-IP rate limit.** 5 queries per IP per 24-hour rolling window, tracked in Cosmos DB.
- **AP-3: Global daily cap.** Hard limit on total queries served per day across all IPs.
- **AP-4: Application-level circuit breaker.** Python backend tracks daily Gemini call count, refuses LLM calls past threshold.
- **AP-5: No billing on Gemini Google Cloud project.** Gemini returns 429 errors when free tier exhausted instead of charging.
- **AP-6: Azure budget with email alerts.** Set at Rs 500/month with alerts at 50%, 75%, 90%, 100%.
- **AP-7: Azure Automation runbook auto-stop.** Triggered at 100% budget hit, scales Container Apps to zero.

---

## 5. Evaluation Requirements

- **EV-1: Eval set size.** 50-100 questions with verified ground-truth answers.
- **EV-2: Eval set categories.** Four buckets: ingredient analysis (theft vs robbery vs dacoity), sentencing and bail jurisprudence, IPC-to-BNS mapping, out-of-scope rejection.
- **EV-3: Eval set format.** JSONL file with `id`, `category`, `question`, `expected_sections`, `expected_cases`, `expected_answer_themes`, `reviewed_by`, `reviewer_notes`.
- **EV-4: Automated eval script.** Reports retrieval@5, citation accuracy, out-of-scope rejection rate, latency p50/p95, per-category breakdowns.
- **EV-5: Human review.** At least 10-15 questions spot-checked by a law student or junior lawyer. Reviewer credited in README.
- **EV-6: LLM-as-judge.** Secondary automated grading using Gemini.
- **EV-7: Failure analysis.** Dedicated README section documenting 5-10 questions where the system underperforms.

---

## 6. Repository & Documentation Requirements

- **DOC-1:** Public GitHub repository, MIT license.
- **DOC-2:** Polished README: hero (description, badges, demo GIF, live link), problem statement, architecture diagram, tech stack, evaluation results, design decisions FAQ, known limitations, local development guide, cost analysis breakdown.
- **DOC-3:** Architecture diagram (SVG or PNG) showing the full system.
- **DOC-4:** Demo GIF, 30-60 seconds, embedded at top of README.
- **DOC-5:** CONTRIBUTING.md with `good-first-issue` labels on a few issues.
- **DOC-6:** Clean commit history with meaningful messages.
- **DOC-7:** CI/CD from day one — working pipeline from the first commit.

---

## 7. Services & Tech Stack

### 7.1 AI / RAG Layer

| Component | Service | Cost |
|---|---|---|
| Generation LLM | Google Gemini 1.5 Flash | Free tier |
| Embeddings | Google Gemini `text-embedding-004` | Free tier |
| Vector database | ChromaDB embedded, baked into Docker image | Rs 0 |
| Retrieval | Hybrid: vector similarity + BM25 keyword | Rs 0 |
| Scope rejection | Embedding similarity threshold | Rs 0 |
| Caching | Two-layer (exact + semantic) in Cosmos DB | Rs 0 |

### 7.2 Azure Infrastructure

| Component | Service | Cost |
|---|---|---|
| Frontend hosting | Azure Static Web Apps (free tier) | Rs 0 |
| Backend compute | Azure Container Apps (scale-to-zero) | Rs 0-100/month |
| Database | Azure Cosmos DB free tier (1000 RU/s, 25GB) | Rs 0 |
| Secrets management | Azure Key Vault (with managed identity) | ~Rs 50/month |
| Logging | Azure Log Analytics workspace | ~Rs 50-100/month |
| Monitoring | Azure Application Insights (free tier) | Rs 0 |
| Budgets & alerts | Azure Cost Management | Rs 0 |
| Auto-stop kill switch | Azure Automation runbook | ~Rs 0-20/month |

### 7.3 External Services

| Component | Service | Cost |
|---|---|---|
| Abuse protection | Cloudflare Turnstile | Free |
| Source control & CI/CD | GitHub + GitHub Actions (public repo) | Free |
| Uptime / keep-warm | UptimeRobot (5-min pings) | Free |
| Domain | Free `.azurestaticapps.net` subdomain | Rs 0 |

### 7.4 Application Stack

| Layer | Technology |
|---|---|
| Frontend framework | React (Vite) |
| Frontend styling | Tailwind CSS |
| Backend framework | Python — FastAPI |
| Embeddings | Gemini embeddings API |
| Vector DB client | `chromadb` |
| Gemini client | `google-generativeai` |
| Cosmos client | `azure-cosmos` |
| Key Vault client | `azure-identity` + `azure-keyvault-secrets` |
| Container base | `python:3.11-slim`, multi-stage Docker build |
| CI/CD authentication | OIDC federation between GitHub and Azure |

---

## 8. Data & Corpus Requirements

- **CORP-1: Statutory sources.** BNS 2023 Sections 303-313, IPC 1860 Sections 378-402 (transition mapping), relevant BNSS 2023 and BSA 2023 provisions. Acquired as **PDFs** from indiacode.nic.in (canonical), with spot-checks against indiankanoon.org and prsindia.org. Three files total, manually downloaded.
- **CORP-2: Case law sources.** **30-70 judgments** from the Supreme Court and High Courts (Delhi, Bombay, Madras, Calcutta, Allahabad, and others), filtered via Indian Kanoon search using the keyword combination `"robbery" + "conviction"`. Manually downloaded one-by-one via the browser; no automated scraping. Sorted by Indian Kanoon's "Most Cited" to surface the doctrinally important cases first.
- **CORP-3: Dual-format archival.** Each judgment is saved in **both HTML and PDF** formats. HTML is the primary source for parsing, chunking, and indexing. PDF is the authoritative archival copy and is what gets linked in answer citation cards for users who want to read the official version. Only HTML is indexed in ChromaDB to avoid double-counting embeddings.
- **CORP-4: Repository folder layout.** Corpus lives at the **repository root** under `data/`. The 3 bare-act PDFs sit at the top level of `data/`; the 30-70 judgments live in numbered subfolders. No `acts/` or `judgments/` subdirectories.

  ```
  data/
  ├── bns_2023.pdf                                           <- bare acts at top level
  ├── ipc_1860.pdf
  ├── bnss_2023.pdf
  ├── 01/                                                    <- numbered case folders
  │   ├── phool_kumar_vs_delhi_administration_1975.html
  │   └── phool_kumar_vs_delhi_administration_1975.pdf
  ├── 02/
  │   ├── dilawar_singh_vs_state_of_delhi_2007.html
  │   └── dilawar_singh_vs_state_of_delhi_2007.pdf
  └── ... (numbered folders 01-NN, one per judgment)
  ```

  Top-level PDFs are bare acts; they bypass the relevance classifier (always indexed). Numbered subfolders are judgments; they go through relevance classification. The asymmetry is intentional and self-documenting: anything in a numbered folder is "evidence that needs classifying"; anything at the root is "authoritative reference material."

  The `data/` directory IS committed to the repo (the raw corpus is part of the deliverable). It is distinct from `chroma_db/`, which is the built index and is gitignored (rebuilt on each ingestion).

- **CORP-5: Filename normalization rules.** Every PDF at the top level of `data/` and every file inside `data/<NN>/` follows a strict naming convention applied when saving from the browser:
    - All lowercase
    - Spaces replaced with single underscore (`_`)
    - Punctuation removed: `.`, `,`, `&`, `'`, `"`, `(`, `)`, `:`, `;`, `?`, `!`, `/`, `\`
    - Multiple consecutive underscores collapsed to one
    - Leading and trailing underscores stripped
    - File extension lowercased
    - For judgments only: HTML and PDF inside the same numbered folder share the **identical base name**, differing only in extension. (This pairing rule does not apply to top-level act PDFs.)
    - Examples:
      - `Bharatiya Nyaya Sanhita 2023.pdf` → `bharatiya_nyaya_sanhita_2023.pdf` (or rename to `bns_2023.pdf` for brevity)
      - `Phool Kumar vs Delhi Administration on 13 March, 1975.html` → `phool_kumar_vs_delhi_administration_on_13_march_1975.html`

  The `scripts/normalize_filenames.py` tool applies these rules deterministically with a dry-run mode and pairing verification. The `verify_corpus.py` script enforces them as a hard check during ingestion.

- **CORP-6: Relevance filtering via LLM classifier (Option C).** After bulk download, every saved judgment passes through a Gemini-based relevance classifier (offline, run once, free tier) that asks: *"Is this judgment substantively about robbery under IPC §§390-402 or BNS §§309-311? Reply with a JSON object containing `is_relevant` (bool), `relevance_score` (0-1), and `reasoning` (one sentence)."* Results are written back to `sources.yaml` under `relevance_classifier_status` and `relevance_score`. Cases scoring below 0.6 are excluded from indexing; cases between 0.6 and 0.8 are flagged for human review; cases above 0.8 are indexed automatically.
- **CORP-7: Chunking strategy.** Bare acts chunked per section with subsection metadata; judgments chunked per paragraph or logical argument unit (~300-500 tokens) preserving paragraph numbers from the original HTML. Metadata on every chunk: `{source_type, case_id, case_name, section_or_paragraph, citation, year, court, outcome, indian_kanoon_url, html_path, pdf_path}`.
- **CORP-8: Ingestion pipeline.** One-time offline script run locally. Reads from `data/`, outputs `chroma_db/` folder baked into Docker image. No runtime ingestion, no live scraping.
- **CORP-9: Corpus refresh strategy.** Annual baseline, on-demand for major amendments. Stated in README.
- **CORP-10: Corpus version tracking.** Every chunk and cache entry tagged with `corpus_version`. Cache invalidates on version bump.
- **CORP-11: Sources manifest schema.** A `sources.yaml` file at the repo root (or `data/sources.yaml`) is the authoritative manifest. One entry per case folder. Each entry includes:

  ```yaml
  - folder: "01"                              # matches data/01/
    case_id: "01"                             # folder number as ID for code
    case_name: "Shri Phool Kumar v. Delhi Administration"
    citation: "(1975) 1 SCC 797 / AIR 1975 SC 905"
    court: "Supreme Court of India"
    year: 1975
    primary_section: "397 IPC"
    other_sections: ["392 IPC", "342 IPC"]
    outcome: "conviction-upheld"              # conviction-upheld | conviction-set-aside | bail-granted | bail-denied | other
    indian_kanoon_url: "https://indiankanoon.org/doc/1212588/"
    indian_kanoon_doc_id: "1212588"
    html_filename: "phool_kumar_vs_delhi_administration_on_13_march_1975.html"
    pdf_filename: "phool_kumar_vs_delhi_administration_on_13_march_1975.pdf"
    retrieved_date: "2026-05-15"
    html_sha256: null                         # filled by verify_corpus.py
    pdf_sha256: null                          # filled by verify_corpus.py
    relevance_classifier_status: "pending"    # pending | approved | rejected | needs-review
    relevance_score: null                     # 0.0-1.0, filled by classifier
    classifier_reasoning: null                # one-sentence justification from Gemini
    manual_review_notes: null
  ```

  The bare acts have a separate, simpler manifest stanza (`acts:` section in the same YAML) since they don't need relevance classification.

- **CORP-12: Storage footprint estimate.** ~3 PDFs (acts, ~10 MB total) + ~30-70 judgments × (HTML ~100KB + PDF ~600KB) ≈ ~20-50 MB of raw corpus committed to the repo. ChromaDB index: ~15-30 MB. Total Docker image impact: ~30-60 MB additional over the base Python image. Acceptable for portfolio scale.

- **CORP-13: Docker COPY contract.** The backend Dockerfile must `COPY data/ /app/data/` (raw corpus, read-only at runtime, used only if re-ingestion is triggered) AND `COPY chroma_db/ /app/chroma_db/` (the built index, what runtime retrieval actually queries). Both paths are baked into the image; neither is mounted as a volume.

---

## 9. Cosmos DB Schema

Single Cosmos account, single database, **single container** with type-discriminated documents (cheaper RU/s than multiple containers). Partition key: `/pk`.

| Document type | Partition key | ID | Key fields | TTL |
|---|---|---|---|---|
| `rate_limit` | `"rate:" + hash(IP)` | date bucket | `count`, `last_query_at` | 48h |
| `query_log` | `"log:" + date` | uuid | `timestamp`, `hashed_ip`, `question`, `response`, `citations`, `latency_ms`, `cache_hit`, `rejected` | 90d |
| `cache_exact` | `"cache:exact"` | hash of normalized query | `response`, `citations`, `corpus_version`, `created_at` | none |
| `cache_semantic` | `"cache:semantic"` | uuid | `query_embedding`, `response`, `citations`, `corpus_version` | none |
| `global_counter` | `"global"` | date | `total_queries`, `total_llm_calls`, `total_rejected`, `total_cache_hits` | none |

---

## 10. System Architecture

### 10.1 High-Level Flow

```
[User Browser]
     |
     v
[Azure Static Web Apps]  -- serves React SPA
     |
     | /api/* proxied via Backend Linking
     v
[Azure Container Apps]   -- FastAPI backend (scale-to-zero)
     |
     +--> [Cloudflare Turnstile]   verify token
     +--> [Azure Cosmos DB]        rate limits, cache, query logs
     +--> [ChromaDB embedded]      vector + BM25 retrieval
     +--> [Gemini API]             embeddings + generation
     +--> [Azure Key Vault]        secrets (managed identity)
     +--> [App Insights]           telemetry
```

### 10.2 Request Lifecycle (Happy Path)

1. User submits question from React UI; Turnstile token attached to request.
2. SWA proxies `/api/query` to Container Apps backend with `x-forwarded-for` header.
3. Backend verifies Turnstile token with Cloudflare API. Reject if invalid.
4. Backend hashes IP (SHA-256 + salt), checks rate limit in Cosmos. Reject if exhausted.
5. Backend checks global daily cap. Reject if exceeded.
6. Backend normalizes query, checks exact-match cache. Hit → return cached response.
7. Backend embeds query via Gemini embeddings API.
8. Backend checks semantic cache using embedding. Hit (similarity > 0.92) → return cached response.
9. Backend performs hybrid retrieval (BM25 + vector) against ChromaDB. Top-k=20.
10. Backend checks top result similarity. If below scope threshold → reject as out-of-scope, do NOT count toward rate limit.
11. Backend re-ranks or truncates to top-5, builds augmented prompt.
12. Backend calls Gemini generation with prompt + retrieved context.
13. Backend verifies every citation in response against retrieved chunk set. Strip invalid.
14. Backend writes query log, increments counters, stores cache entry.
15. Backend returns response to frontend. React renders answer + expandable citation cards.

### 10.3 Deployment Pipeline

- **Frontend:** Push to `main` → GitHub Actions builds Vite → deploys to SWA.
- **Backend:** Push to `main` → GitHub Actions builds Docker → pushes to Azure Container Registry → updates Container Apps revision.
- **Authentication:** OIDC federation between GitHub and Azure (no stored secrets).

### 10.4 Corpus Lifecycle

- Raw corpus lives at the **repo root** under `data/` (acts + judgments, both HTML and PDF). Committed to the repo. This is the input.
- Ingestion runs locally on developer machine. Reads `data/`, applies relevance classifier, normalizes, chunks, embeds, indexes.
- Output: `chroma_db/` folder with embedded vector index + `bm25.pkl` for keyword search. The output is gitignored — it is rebuilt by `make ingest` whenever the corpus changes.
- Both `data/` (input, committed) and `chroma_db/` (output, gitignored but baked at image-build time) are `COPY`ed into the backend Docker image.
- Corpus version bump (`CORPUS_VERSION` constant in `backend/app/constants.py`) triggers backend redeploy → cache implicitly invalidates via `corpus_version` field on every cache entry.

---

## 11. Build Methodology

### 11.1 Batch / Chunk Structure

The project is delivered in **batches**. Each batch is a logical phase of work (e.g., "Backend Core Pipeline"). Each batch contains **chunks**. Each chunk delivers **at most 4 files**.

**Rules:**
- Maximum 4 files per chunk.
- Soft cap: 300 lines per file. Files exceeding 300 lines must be split across modules.
- Hard cap: 500 lines per file. Never exceeded.
- Chunks are sequenced — earlier chunks must run/compile before later chunks build on them.
- Each chunk is self-contained as far as practical; integration points are explicit.

### 11.2 Frontend Exception

The React frontend is **not** delivered in 4-file chunks. It ships as a **single ZIP file** generated in one go. Rationale: React projects have many small interdependent files (components, hooks, styles, routes) where artificial 4-file boundaries would fragment the structure and confuse review.

The ZIP contains a full Vite + React + Tailwind project ready to `npm install && npm run dev`.

### 11.3 Delivery Format Per Chunk

Each chunk delivery includes:
- File path (absolute, from repo root)
- Full file contents
- Brief note on what the chunk accomplishes and what the next chunk depends on

### 11.4 Definition of Done Per Batch

Each batch ends with a verification step: a command or test the user runs locally to confirm everything wired up correctly before the next batch begins.

---

## 12. Batch & Chunk Plan

Below is the complete batch breakdown with chunks and files for each. File counts in parentheses.

> Note: Frontend (Batch 6) is delivered as a single ZIP and is not chunked.

### Batch 0 — Repo Scaffolding & CI/CD Bootstrap

**Goal:** Empty repository with working CI/CD, license, README skeleton, and folder structure. Working from day one means everything we build flows through the pipeline.

| Chunk | Files |
|---|---|
| 0.1 — Repo essentials | `README.md` (skeleton), `LICENSE` (MIT), `.gitignore`, `CONTRIBUTING.md` |
| 0.2 — Folder structure & placeholders | `backend/README.md`, `frontend/README.md`, `ingestion/README.md`, `eval/README.md` |
| 0.3 — GitHub Actions (backend) | `.github/workflows/backend-ci.yml`, `.github/workflows/backend-deploy.yml`, `infra/azure-oidc-setup.md`, `infra/.gitkeep` |
| 0.4 — GitHub Actions (frontend) | `.github/workflows/frontend-ci.yml`, `.github/workflows/frontend-deploy.yml`, `staticwebapp.config.json`, `.github/dependabot.yml` |

**Verification:** Push to repo, both workflows run green on the empty scaffolds.

### Batch 1 — Corpus & Evaluation Set

**Goal:** Legal corpus manually collected from Indian Kanoon (HTML + PDF) into `data/01..NN/` plus 3 bare-act PDFs at `data/` root, classified for relevance via Gemini, normalized, chunked into a JSONL format. 50-100 eval questions drafted in JSONL.

| Chunk | Files |
|---|---|
| 1.1 — Manifest & download playbook | `sources.yaml` (template + schema, at repo root), `scripts/normalize_filenames.py` (filename normalizer with dry-run), `ingestion/collect/verify_corpus.py`, `ingestion/collect/README.md` (methodology + download_checklist) |
| 1.2 — Relevance classifier | `ingestion/classify/relevance_classifier.py` (Gemini prompt + JSON parsing), `ingestion/classify/run_classifier.py` (orchestrator that writes scores back to sources.yaml), `ingestion/classify/prompts.py`, `ingestion/classify/README.md` |
| 1.3 — Corpus normalization | `ingestion/normalize/clean_html.py` (BeautifulSoup judgment extractor reading from `data/<NN>/*.html`), `ingestion/normalize/parse_acts_pdf.py` (statute parser reading from `data/*.pdf` at top level), `ingestion/normalize/parse_judgments.py`, `ingestion/normalize/schema.py` |
| 1.4 — Chunking pipeline | `ingestion/chunk/chunker.py`, `ingestion/chunk/metadata.py`, `ingestion/chunk/run_chunking.py`, `data/.gitkeep` |
| 1.5 — Eval set v1 | `eval/robbery_questions.jsonl` (50-100 questions), `eval/schema.md`, `eval/categories.md`, `eval/REVIEW_NOTES.md` |

**Manual prerequisite (between chunks 1.1 and 1.2):** Developer manually downloads 30-70 judgments (HTML + PDF each) from Indian Kanoon into numbered folders `data/01/`, `data/02/`, ..., following the playbook in `ingestion/collect/README.md`. Filenames normalized per CORP-5 rules (using `scripts/normalize_filenames.py`). Plus 3 bare-act PDFs downloaded from indiacode.nic.in into `data/` (top level): `bns_2023.pdf`, `ipc_1860.pdf`, `bnss_2023.pdf`. Each judgment entry recorded in `sources.yaml` with `relevance_classifier_status: pending`. Acts have a separate, simpler manifest entry that bypasses the classifier.

**Verification:** (a) `python ingestion/collect/verify_corpus.py` confirms folder structure, filename conventions, pairing of HTML+PDF per folder, and populates SHA-256 hashes. (b) `python ingestion/classify/run_classifier.py` populates relevance scores for every entry. (c) `python ingestion/chunk/run_chunking.py` produces `chunks.jsonl` from only `approved` entries (score ≥ 0.6). (d) Eval set parses as valid JSONL with all required fields.

### Batch 2 — Ingestion to ChromaDB

**Goal:** Chunks embedded via Gemini, indexed in ChromaDB with both vector and BM25 indices, folder ready to bake into Docker image.

| Chunk | Files |
|---|---|
| 2.1 — Embedding client | `ingestion/embed/gemini_client.py`, `ingestion/embed/embed_chunks.py`, `ingestion/embed/cache.py`, `ingestion/embed/README.md` |
| 2.2 — ChromaDB index builder | `ingestion/index/build_chroma.py`, `ingestion/index/build_bm25.py`, `ingestion/index/corpus_version.py`, `ingestion/index/verify_index.py` |
| 2.3 — Ingestion orchestrator | `ingestion/run_ingestion.py`, `ingestion/config.py`, `ingestion/requirements.txt`, `ingestion/Makefile` |

**Verification:** Run `make ingest`. Output is a `chroma_db/` folder plus `bm25.pkl`. Querying it locally returns sensible top-k results.

### Batch 3 — Backend Core (RAG Pipeline)

**Goal:** Standalone backend module that can take a question and produce an answer with citations, no HTTP layer yet.

| Chunk | Files |
|---|---|
| 3.1 — Config & clients | `backend/app/config.py`, `backend/app/clients/gemini.py`, `backend/app/clients/chroma.py`, `backend/app/clients/cosmos.py` |
| 3.2 — Retrieval | `backend/app/rag/retrieval.py`, `backend/app/rag/bm25.py`, `backend/app/rag/hybrid.py`, `backend/app/rag/scope.py` |
| 3.3 — Generation & citation | `backend/app/rag/prompt.py`, `backend/app/rag/generate.py`, `backend/app/rag/citations.py`, `backend/app/rag/pipeline.py` |
| 3.4 — Caching layer | `backend/app/cache/exact.py`, `backend/app/cache/semantic.py`, `backend/app/cache/manager.py`, `backend/app/cache/keys.py` |

**Verification:** Run `python -m backend.app.rag.pipeline "What is robbery?"` and get a structured response with citations.

### Batch 4 — Backend Service (HTTP, Rate Limit, Abuse Protection)

**Goal:** FastAPI service exposing `/api/query` and `/api/health`, with Turnstile, rate limiting, circuit breaker, and global cap.

| Chunk | Files |
|---|---|
| 4.1 — FastAPI app skeleton | `backend/app/main.py`, `backend/app/routes/query.py`, `backend/app/routes/health.py`, `backend/app/middleware/request_context.py` |
| 4.2 — Rate limiting & IP handling | `backend/app/security/ip.py`, `backend/app/security/rate_limit.py`, `backend/app/security/global_cap.py`, `backend/app/security/circuit_breaker.py` |
| 4.3 — Turnstile & request validation | `backend/app/security/turnstile.py`, `backend/app/schemas/request.py`, `backend/app/schemas/response.py`, `backend/app/errors.py` |
| 4.4 — Logging & telemetry | `backend/app/telemetry/app_insights.py`, `backend/app/telemetry/query_log.py`, `backend/app/telemetry/counters.py`, `backend/app/telemetry/cost_tracker.py` |

**Verification:** Run backend locally with `uvicorn backend.app.main:app`. POST to `/api/query` with valid Turnstile token returns answer. Rate limit triggers after 5 requests.

### Batch 5 — Backend Admin & Packaging

**Goal:** Analytics dashboard endpoint, password protection for `/admin`, Docker image with ChromaDB baked in, ready to deploy.

| Chunk | Files |
|---|---|
| 5.1 — Admin endpoints | `backend/app/routes/admin.py`, `backend/app/admin/queries.py`, `backend/app/admin/metrics.py`, `backend/app/admin/auth.py` |
| 5.2 — Docker packaging | `backend/Dockerfile`, `backend/.dockerignore`, `backend/requirements.txt`, `backend/entrypoint.sh` |
| 5.3 — Local dev tooling | `backend/Makefile`, `backend/docker-compose.yml`, `backend/.env.example`, `backend/tests/test_smoke.py` |

**Verification:** `docker build` succeeds. `docker run` serves requests locally. `/admin` requires password.

### Batch 6 — Frontend (Single ZIP Delivery)

**Goal:** Complete React + Tailwind frontend, ready to deploy to Azure Static Web Apps.

**Delivery:** Single `frontend.zip` containing a full Vite project with:
- Pages: Home (query + answer), Admin dashboard, Terms of Use
- Components: query box, answer display, citation cards (expandable), disclaimer banner, first-visit modal, rate-limit countdown, scope-rejection panel with suggestions, cold-start loader, error fallback
- State: React Context for query state, error state, disclaimer-accepted flag (localStorage)
- API client: typed wrapper around backend endpoints, Turnstile integration
- Styling: Tailwind config with custom theme tokens
- Build: Vite config tuned for SWA, env var handling, `npm run build` produces `/dist`

**Verification:** Unzip, `npm install`, `npm run dev`. UI loads, connects to local backend, full happy path works end-to-end.

### Batch 7 — Azure Infrastructure as Code

**Goal:** All Azure resources provisioned reproducibly. Anyone with an Azure subscription can deploy from scratch.

| Chunk | Files |
|---|---|
| 7.1 — Core resources (Bicep or scripts) | `infra/main.bicep`, `infra/parameters.json`, `infra/modules/cosmos.bicep`, `infra/modules/key-vault.bicep` |
| 7.2 — Compute & hosting | `infra/modules/container-apps.bicep`, `infra/modules/container-registry.bicep`, `infra/modules/static-web-app.bicep`, `infra/modules/log-analytics.bicep` |
| 7.3 — Cost protection | `infra/modules/budget-alerts.bicep`, `infra/automation/auto-stop.ps1`, `infra/automation/runbook-setup.md`, `infra/manual-kill-switch.md` |
| 7.4 — Deploy & teardown scripts | `infra/deploy.sh`, `infra/teardown.sh`, `infra/post-deploy-checklist.md`, `infra/README.md` |

**Verification:** Run `./infra/deploy.sh` against a clean subscription. All resources come up. Smoke test passes against deployed endpoints.

### Batch 8 — Evaluation Harness & Final Polish

**Goal:** Automated eval script, LLM-as-judge integration, results published in README, demo GIF recorded.

| Chunk | Files |
|---|---|
| 8.1 — Eval runner | `eval/run_eval.py`, `eval/metrics.py`, `eval/llm_judge.py`, `eval/report_template.md` |
| 8.2 — Failure analysis & docs | `eval/results/baseline.json`, `eval/results/failure_analysis.md`, `eval/results/category_breakdown.md`, `docs/architecture.md` |
| 8.3 — README final + GIF | `README.md` (full polished version), `docs/cost-analysis.md`, `docs/design-decisions.md`, `docs/demo.gif` (binary placeholder noted in code) |

**Verification:** `python eval/run_eval.py` produces metrics report. README renders correctly on GitHub. Demo GIF plays on README page.

---

## 13. Timeline & Milestones

**Total duration:** 5-7 weeks of evenings/weekends.

| Week | Milestone | Batches |
|---|---|---|
| 1 | Foundation & Eval | 0, 1 |
| 2 | RAG core working locally | 2, 3 |
| 3 | Backend service running locally | 4 |
| 4 | Backend dockerized + admin | 5 |
| 5 | Frontend complete, integrated | 6 |
| 6 | Deployed to Azure end-to-end | 7 |
| 7 | Evaluation + polish + launch | 8 |

**Front-load weeks 1-2:** corpus + eval set + Azure infra exploration. These are the highest-risk, lowest-motivation pieces. Doing them while energy is high prevents the late-project death spiral.

---

## 14. Out of Scope (Explicit Non-Goals)

Stated clearly so we don't drift:

- Multi-turn conversation (single-turn only for v1)
- Other offence categories (robbery only)
- User accounts, history, saved queries (anonymous only)
- Mobile apps (web only; mobile responsive web is fine)
- Multilingual support (English only for v1)
- Real-time corpus updates (annual refresh only)
- Production-grade SLA (best-effort)
- Legal advice or recommendations (research assistance only, with prominent disclaimers)
- Lawyer marketplace, case filing, document generation

---

## 15. Cost Summary

| Cost center | Estimated monthly (Rs) |
|---|---|
| Gemini LLM + embeddings | 0 (free tier) |
| Azure Container Apps | 0-100 |
| Azure Static Web Apps | 0 (free tier) |
| Azure Cosmos DB | 0 (free tier) |
| Azure Key Vault | ~50 |
| Azure Log Analytics | ~50-100 |
| Azure Automation | 0-20 |
| Cloudflare Turnstile | 0 |
| GitHub Actions | 0 (public repo) |
| UptimeRobot | 0 |
| Domain | 0 (free subdomain) |
| **Total** | **100-270** |

**Headroom against Rs 500 budget:** ~Rs 230-400/month. Comfortable.

---

## Appendix A — Build Order Quick Reference

```
Batch 0  →  Batch 1  →  Batch 2  →  Batch 3  →  Batch 4  →  Batch 5  →  Batch 6  →  Batch 7  →  Batch 8
Scaffold    Corpus      Index       RAG core    Service     Pkg+Admin   Frontend    Infra       Eval+polish
                                                                        (ZIP)
```

Total chunks across batches: **31 chunks** + 1 frontend ZIP delivery.

---

*End of design document. Last updated: data folder layout flattened — bare-act PDFs (BNS, IPC, BNSS) sit at `data/` root; judgments in numbered folders `data/01/`..`data/NN/` (no `acts/` or `judgments/` subdirectories); top-level PDFs bypass the relevance classifier; verified direct PDF URLs from indiacode.nic.in documented in `ingestion/collect/README.md`; `scripts/normalize_filenames.py` handles both top-level acts and judgment files. Update this file when scope or sequencing changes.*
