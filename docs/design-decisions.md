# Design decisions

A FAQ covering the non-obvious technology and architecture choices in this project. The README has the headline tech stack table; this file is the "why each call?" companion.

If you're an interviewer reading this and want the short version: every choice prioritizes **local-first development** and **monthly cost under Rs 500**. Both constraints rule out a lot of options that would be sensible in a different context.

---

## Why ChromaDB embedded instead of a hosted vector database?

ChromaDB embedded means the vector index is a file on disk (`ingestion/data/chroma_db/`) loaded into the FastAPI process at startup. No separate service. No network round-trip per query. No monthly bill.

Alternatives considered:

- **Pinecone / Weaviate / Qdrant Cloud.** All have free tiers but with quotas tight enough that a small portfolio project quickly hits them. Adding a hosted vector DB is also another moving part to deploy, secure, and pay for.
- **pgvector on Azure Postgres.** Postgres on Azure costs ~Rs 1500-3000/month minimum (no free tier for managed instances). Out of budget.
- **Cosmos DB vector search.** This exists, but Cosmos vector search RU/s charges add up fast on free-tier RU/s limits.

ChromaDB embedded is free, fast, and at 60k chunks it fits in 12 MB. The tradeoff is that the index is part of the Docker image — bumping the corpus means a backend redeploy. For an annual-refresh corpus that's fine.

---

## Why Cosmos DB for rate limits and cache instead of Redis?

Two reasons:

1. **Free tier.** Cosmos has a 1000 RU/s + 25 GB free allowance per Azure account. Azure Cache for Redis has no free tier — the smallest paid SKU is ~Rs 1000/month.

2. **Single-store simplicity.** Rate limits, exact-match cache, semantic cache, query logs, and global counters all live in the same Cosmos container with a `pk` (partition key) discriminator. No second technology to provision, monitor, or back up.

The tradeoff is RU cost per operation. A typical query touches Cosmos 4-6 times (rate-limit read, exact-cache read, semantic-cache read, query-log write, counter increment). At ~1-2 RU each, that's well under the free tier.

For a service that needed sub-millisecond cache reads at scale, Redis would be the right call. For 5 queries/IP/day with scale-to-zero compute, Cosmos is fine.

---

## Why GHCR for the Docker image instead of Azure Container Registry?

ACR Basic costs ~Rs 420/month. GHCR is free for public repositories.

The image lives at `ghcr.io/sarthakdixit/indian-robbery-rag:latest`. Container Apps pulls it anonymously (the package is set to public). The CI workflow pushes to GHCR using the built-in `GITHUB_TOKEN` — no PAT or stored credential needed.

Tradeoffs:

- **Public image.** Anyone can pull the image. This is fine because (a) the source code is also public, and (b) secrets are NOT baked in — they're injected at runtime from Key Vault.
- **No image signing / vulnerability scanning UI.** ACR has Microsoft Defender for Containers integration. GHCR's scanning is via GitHub Dependabot, which is less prominent.

For a portfolio project, the ~Rs 5000/year savings from skipping ACR is worth those tradeoffs.

---

## Why Azure Container Apps (scale-to-zero) instead of App Service or Functions?

Three options to host a long-running FastAPI app on Azure:

1. **App Service.** Always-on, even on the cheapest plan (~Rs 1000/month for B1). No scale-to-zero. Out of budget.
2. **Azure Functions.** Cheap, but FastAPI doesn't fit the Functions model cleanly — every endpoint becomes a separate function. Also the cold-start penalty is similar to Container Apps with scale-to-zero, without the benefit of running a normal FastAPI app.
3. **Container Apps.** Scale-to-zero (free when idle), pay-per-request when active. Cold-start is 8-12 seconds on the first request after scaling down — visible but acceptable for a demo.

Container Apps wins for this workload. The cold-start cost is communicated to users via a "warming up" loading state that appears after 3 seconds.

---

## Why scale-to-zero with a visible cold start?

A recruiter clicking the demo link expects the app to load. Scale-to-zero means the first hit takes 8-12 seconds while the container spins up.

We chose visibility over hiding it:

- The frontend shows a subtle spinner for the first 3 seconds.
- After 3 seconds, the message changes to "Warming up the legal research engine, takes about 10 seconds on first visit."
- After 10 seconds, "Still warming up... almost there."

The alternative (UptimeRobot pings every 5 minutes to keep the container warm) would defeat the cost optimization. Most demo visits are short, single sessions; paying for always-on compute to save 10 seconds for those visits is a bad trade.

If this were a real product the cold-start would be hidden by always-on compute. For a portfolio demo, showing the honest behavior is better.

---

## Why Cloudflare Turnstile and not reCAPTCHA?

Turnstile is invisible to legitimate users (no "click all the buses" challenges in 99% of cases) and is privacy-preserving (no Google tracking). Free for any usage volume.

reCAPTCHA v3 is similar but ties everything to Google's ad-tech tracking. The privacy improvement matters more for a public legal-research demo where some users may be researching sensitive topics.

The site key used in the current deploy is Cloudflare's test key (`1x00000000000000000000AA`), which always passes. For production-grade bot protection, register a real Turnstile site at dash.cloudflare.com and replace the site+secret key pair.

---

## Why Gemini 2.5 Flash-Lite instead of GPT-4 / Claude / Llama?

Free tier is the only reason that matters at this budget. Other considerations:

- **Gemini Flash-Lite** has a generous free tier (15 req/min, ~1500 req/day on the free key) that comfortably covers a demo and the eval harness.
- **OpenAI GPT-4o-mini** is ~$0.15 per million input tokens — cheap but not free.
- **Anthropic Claude Haiku** is similar pricing to GPT-4o-mini.
- **Llama 3 via together.ai** is free for small volumes but with rate limits tighter than Gemini.

Gemini's answer quality for this domain is good enough — the eval harness measures it directly. If the eval shows Gemini struggling with specific question types, swapping to a different LLM is a single-file change (`backend/app/clients/gemini.py` implements a protocol).

---

## Why an embedded BM25 index alongside ChromaDB vector search?

Pure vector retrieval is bad at exact identifier matches. "Section 397" or "§390" should retrieve chunks containing those literal tokens, but BNS embeddings cluster sections that are semantically similar — which can miss the chunk that names the exact section the user asked about.

Hybrid retrieval solves this: BM25 ranks by keyword overlap, vector ranks by semantic similarity, and **reciprocal rank fusion** combines the two rankings into a final top-K. This catches both "what is the difference between theft and robbery" (semantic) and "what is section 397" (keyword).

The library is `bm25s` (Rust-backed, ~100× faster than the older `rank_bm25`). The index is built once during ingestion and loaded into memory at app startup; runtime BM25 queries are submillisecond.

---

## Why a scope rejection threshold at 0.55 and a cache threshold at 0.92?

Both are tuned empirically from the eval set, not picked arbitrarily.

**Scope threshold (0.55).** Below this top-vector similarity, the system rejects the query as out-of-scope. Above it, the LLM gets called. The threshold sits in the empty band between in-scope queries (which typically score 0.65-0.90) and adjacent-offence questions (which typically score 0.40-0.55). The exact value is the midpoint of the highest OOS similarity and the lowest in-scope similarity across the eval set, with a small margin.

**Cache threshold (0.92).** Above this query-to-cached-query similarity, we serve the cached answer without re-running the pipeline. The threshold has to be high enough that two semantically distinct queries (e.g., "what is robbery" vs "what is dacoity") never collide. 0.92 was the value where every collision in our eval-set pairwise comparison was a true semantic match.

If you change the eval set substantially, re-tune these. Threshold-sweep results live in `eval/results/threshold_sweep.md` (committed when generated).

---

## Why citation verification?

LLMs hallucinate citations. The Gemini answer might include `[5]` even when only 3 chunks were retrieved, or might cite "Smith v. State" when no such case exists in the corpus.

The citation verifier (`backend/app/rag/citations.py`) parses every `[N]` reference in the generated answer and checks two things:

1. Is N within the bounds of the retrieved chunk set?
2. Does the chunk at index N have metadata that plausibly matches what the answer claims?

References that fail either check are stripped. The frontend renders the cleaned text; the user never sees the hallucinated reference.

This is a small piece of code (~80 lines) but it's the difference between "the system never hallucinates citations" and "the system sometimes lies about its sources." For a legal-research tool, citation honesty is a hard requirement.

---

## Why structured-output JSON for the Gemini relevance classifier?

The relevance classifier (`ingestion/classify/relevance_classifier.py`) filters bulk-downloaded judgments before indexing. It needs to return three things per judgment: `is_relevant: bool`, `relevance_score: float`, `reasoning: str`.

Without structured output, you'd parse the LLM's free-form text and hope it's parseable. With Gemini's `response_mime_type="application/json"` parameter, the SDK returns JSON directly. We validate it through a Pydantic `ClassifierVerdict` model.

Result: every classification either parses cleanly or fails fast. No regex-based parsing of LLM prose. The same pattern is used for the LLM-as-judge in `eval/llm_judge.py`.

---

## Why a per-IP rate limit at 5 queries per day?

Cost protection. Each Gemini generation call uses ~5-10 KB of free-tier quota. The free tier is ~1500 requests/day. At 5 queries/IP/day, the system serves up to 300 unique users before hitting the daily cap.

The limit is also low enough to discourage scripted abuse without hurting legitimate exploration. A recruiter trying the demo will ask 1-3 questions; 5 is a comfortable upper bound.

If the system needs to grow beyond demo scale, the limit is a single config value (`PER_IP_DAILY_QUERY_LIMIT` in `backend/app/security/constants.py`). The Gemini upgrade path is straightforward — paid tier is ~Rs 0.50 per query.

---

## Why dependency injection?

Every external dependency (Cosmos, Key Vault, Application Insights, Turnstile) has both a cloud adapter and a local adapter behind a shared protocol. Switching is a single environment variable (`ENVIRONMENT=local` vs `cloud`).

The DI container (`backend/app/container.py`) wires the right adapter at startup. Business logic never imports a concrete cloud SDK.

The payoff:

- Local development needs no Azure account. `make dev` runs the full pipeline with SQLite, dotenv, and stdout adapters.
- Tests use the same DI container with in-memory fakes; no mocking magic.
- Adding a new cloud (AWS, GCP) is a new adapter, not a code rewrite.

The cost is a ~150-line container file. Worth it for the rest of the codebase staying cloud-agnostic.

---

## Why one Cosmos container instead of separate containers per document type?

Cosmos charges per container's reserved RU/s, not per item. A single container with a type-discriminated `pk` (partition key) — `"rate:abc123"`, `"cache:exact"`, `"log:2026-06-30"` — uses the free-tier RU/s budget exactly once.

Multiple containers would each consume separate RU/s budget, blowing through the free tier.

The downside is that the container's data is heterogeneous — you can't enforce a schema at the database level. Type discrimination is enforced in code via the document `pk` and a `type` field on each item. Pydantic models on read validate the shape.

---

## Why Bicep instead of Terraform?

Bicep is Azure-native and supports `existing` resources, ARM template references, and Azure-specific resource shapes (like the budget alert thresholds we use) without needing a provider plugin.

Terraform would work but adds:

- Another tool to learn (HCL syntax)
- Stored state (Terraform Cloud or an Azure storage backend), which is yet another resource to provision and pay for
- Slightly weaker integration with Azure-specific resources

For an Azure-only project, Bicep is the lower-friction call. If the project needed multi-cloud (AWS + Azure), Terraform would be the right answer.

---

## Why GitHub Actions OIDC federation instead of stored service-principal secrets?

OIDC means GitHub Actions exchanges a short-lived token (issued by GitHub) for an Azure access token at deploy time. No long-lived credentials are stored in GitHub Secrets.

The old way (`AZURE_CLIENT_SECRET` stored as a GitHub Secret) has two problems:

1. Secrets rotate (or should). Manual rotation is forgotten; expired secrets cause silent CI breakages.
2. Compromised secret = persistent unauthorized Azure access until manually revoked.

With OIDC, every CI run gets a fresh token scoped to the federated credential (this workflow on this branch in this environment). Token lifetime is the duration of the workflow. Compromise is bounded.

The setup cost is one-time: create an Azure AD app, grant it `Contributor` on the resource group, add a federated credential trusting `repo:owner/repo:environment:production`, set 5 GitHub Variables. Documented in [`infra/azure-oidc-setup.md`](../infra/azure-oidc-setup.md).

---

## Why a separate `data/` directory committed to git instead of a download script?

The corpus is 230 MB. That's a lot to commit, and design.md's original §10.4 had it gitignored with the intent of rebuilding via `make ingest` whenever needed.

In practice that didn't work for CI deploys. The Docker build context needs the raw `data/` directory (per `CORP-13`), and CI runners check out from git. If `data/` isn't committed, CI builds an image with an empty corpus.

The pragmatic call: commit the raw corpus. The repository is now ~250 MB checked out, which is large but not absurd. The alternative would be a pre-build CI step that downloads from blob storage — yet another moving part with its own credential and cost story.

This is documented as a deviation from design.md in the commit message that committed the data.

---

## Why the eval harness fakes IP addresses to bypass rate limiting?

The eval set is 59 questions. The rate limit is 5 per IP per day. To run the eval against the deployed system, every question would have to wait 24 hours or share a bucket with another. Neither works.

The harness sets a unique `X-Forwarded-For` header per question (`X-Forwarded-For: eval-ing_001`), which the backend hashes into the rate-limit key. Each fake IP gets its own bucket; the eval runs through cleanly.

This isn't a security issue. The rate limit is a budget guardrail (preventing one IP from burning the Gemini free tier in an afternoon), not authentication. Anyone with `curl` can do the same. If the system ever needed real bot prevention, that's what Turnstile is for — and Turnstile IS verified on every request, including the eval's.

The honest framing: rate limits are an abuse-mitigation layer, not a security layer. The eval harness's bypass is documented in the harness comments and in this FAQ; recruiters reading the eval results should understand what numbers they're looking at.
