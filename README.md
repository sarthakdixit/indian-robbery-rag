# indian-robbery-rag

> A retrieval-augmented question-answering system for Indian robbery law (BNS §§309-311, IPC §§390-402).
> Educational research prototype — **not legal advice**.

<!-- Badges -->
<!-- TODO: Add CI status, license, demo URL once available -->

<!-- Demo GIF -->
<!-- TODO: Replace with a 30-60s screen recording of the system answering a real query. -->
<!-- See design.md DOC-4. Record after Batch 6 (frontend) is integrated end-to-end. -->

🔗 **Live demo:** _coming after Batch 7 (Azure deployment)_

---

## The Problem

<!-- TODO: 2 short paragraphs covering:
       - Indian legal research is slow and fragmented across Indian Kanoon, SCC Online, bare acts
       - The BNS/BNSS transition (in force 1 July 2024) means current cases mix old IPC with new BNS
       - Robbery specifically is a narrow but doctrinally rich area (theft + force/fear, dacoity, deadly weapon)
       - Why a focused RAG system on this slice is more useful than a general legal chatbot
-->

---

## Try It

<!-- TODO: After Batch 7, add example queries the user can click on the landing page:
       - "What is the difference between theft and robbery?"
       - "When does robbery become dacoity?"
       - "Does brandishing a weapon attract Section 397 IPC?"
       - "How is intention to commit theft proved in a robbery case?"
-->

---

## Architecture

<!-- TODO: Embed architecture diagram (SVG or PNG). See design.md §10 for the data flow.
     Generate after Batch 7 is complete. -->

**Stack at a glance**

| Layer            | Choice                                                                                          |
| ---------------- | ----------------------------------------------------------------------------------------------- |
| Frontend         | React + Vite + TypeScript, hosted on Azure Static Web Apps                                      |
| Backend          | Python 3.11 + FastAPI, on Azure Container Apps (scale-to-zero)                                  |
| RAG              | ChromaDB (embedded) + BM25 hybrid retrieval, Gemini 1.5 Flash for generation, Gemini embeddings |
| Storage          | Azure Cosmos DB (free tier) for rate limits, cache, query logs                                  |
| Secrets          | Azure Key Vault with managed identity                                                           |
| Abuse protection | Cloudflare Turnstile + per-IP rate limit + global daily cap + app-level circuit breaker         |
| CI/CD            | GitHub Actions with OIDC federation                                                             |

See [`design.md`](./design.md) for the full architecture and decision log.

---

## Evaluation Results

<!-- TODO: Fill in after Batch 8 with real numbers from eval/run_eval.py.
     Expected sections:
       - Headline metrics: retrieval@5, citation accuracy, out-of-scope rejection rate
       - Per-category breakdown (ingredient analysis, sentencing/bail, IPC-BNS mapping, scope)
       - Failure analysis: 5-10 questions where the system underperforms, with diagnosis
       - Methodology note: eval set spot-checked by [reviewer name and credentials]
-->

_To be populated after Batch 8._

---

## Design Decisions

<!-- TODO: Short FAQ-style entries explaining non-obvious choices.
     Candidate questions:
       - Why robbery only, not all of criminal law?
       - Why ChromaDB embedded instead of a managed vector DB?
       - Why no user login?
       - Why hard-reject out-of-scope queries instead of attempting a best-effort answer?
       - Why Gemini Flash instead of GPT-4 / Claude / self-hosted?
       - Why both HTML and PDF in the corpus?
-->

Full design rationale lives in [`design.md`](./design.md).

---

## Known Limitations

<!-- TODO: Be honest about what the system does NOT do well. Some candidates:
       - Robbery only — anything outside §§309-311 BNS / §§390-402 IPC is rejected
       - Single-turn — no conversation memory
       - English only — no Hindi or regional language support in v1
       - Bail jurisprudence is sparse in the corpus (fact-intensive, not landmark-driven)
       - BNS-era cases are limited (BNS in force only from July 2024)
       - LLM may still produce subtly wrong analysis on ambiguous fact patterns
-->

---

## Local Development

### Prerequisites

- Python 3.11+
- Node.js 20 LTS
- `pnpm` for the frontend (`npm install -g pnpm`)
- A Gemini API key (free tier is sufficient) — get one at https://aistudio.google.com

### Quick start

```bash
git clone https://github.com/<your-username>/indian-robbery-rag.git
cd indian-robbery-rag

# Backend
cd backend
cp .env.example .env  # then add your GEMINI_API_KEY
pip install -r requirements.txt
uvicorn app.main:app --reload

# Frontend (separate terminal)
cd ../frontend
cp .env.example .env
pnpm install
pnpm dev
```

<!-- TODO: Flesh out after Batches 3-6 land. Add:
       - How to run ingestion (build the ChromaDB index from data/)
       - How to run the eval harness
       - How to switch between local and cloud adapters (ENVIRONMENT=local|cloud)
       - How to run tests and linters
-->

Coding conventions live in [`AGENT.md`](./AGENT.md) (Python) and [`AGENT-frontend.md`](./AGENT-frontend.md) (React/TypeScript). Read these before contributing.

---

## Cost Analysis

<!-- TODO: After Batch 7 deployment, populate with real numbers. Per design.md §15.
     Target: ₹100-270/month on Azure free tiers + Key Vault. -->

| Cost center                          | Estimated Rs/month                      |
| ------------------------------------ | --------------------------------------- |
| Gemini LLM + embeddings              | 0 (free tier)                           |
| Azure Container Apps                 | 0–100                                   |
| Azure Static Web Apps                | 0 (free tier)                           |
| Azure Cosmos DB                      | 0 (free tier, 1000 RU/s, 25 GB forever) |
| Azure Key Vault                      | ~50                                     |
| Azure Log Analytics                  | ~50–100                                 |
| Azure Automation (auto-stop runbook) | 0–20                                    |
| Cloudflare Turnstile                 | 0                                       |
| GitHub Actions                       | 0 (public repo)                         |
| **Total**                            | **~100–270**                            |

---

## Project Status

This is an active portfolio project under construction. See [`design.md`](./design.md) for the full batch plan.

- [x] Batch 0 — Repo scaffolding & CI/CD
- [ ] Batch 1 — Corpus & evaluation set
- [ ] Batch 2 — Ingestion to ChromaDB
- [ ] Batch 3 — Backend RAG core
- [ ] Batch 4 — Backend service (HTTP, rate limit, abuse protection)
- [ ] Batch 5 — Backend admin & packaging
- [ ] Batch 6 — Frontend
- [ ] Batch 7 — Azure infrastructure as code
- [ ] Batch 8 — Evaluation harness & polish

---

## Disclaimer

This system is an **educational research prototype**. It is not legal advice and is not a substitute for advice from a qualified advocate. The Bharatiya Nyaya Sanhita, 2023 came into force on 1 July 2024; for offences alleged before that date, the Indian Penal Code, 1860 continues to apply. Always verify with current case law and a qualified advocate.

See [`docs/terms-of-use.md`](./docs/terms-of-use.md) for full terms.

---

## License

MIT — see [`LICENSE`](./LICENSE).

---

## Contributing

Issues and PRs welcome. See [`CONTRIBUTING.md`](./CONTRIBUTING.md) for guidelines and `good-first-issue` labels.
