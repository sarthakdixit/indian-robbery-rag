# Cost analysis

The project was designed to fit within **Rs 500/month**, leaving room for traffic spikes during demo periods. This document breaks down the actual cost picture line by line.

> All figures are in Indian Rupees and based on the Azure Central India region pricing as of 2026-06-30. Exchange rate assumed: $1 ≈ Rs 84.

---

## Summary

| Bucket                          | Monthly cost         | Notes                                                               |
| ------------------------------- | -------------------- | ------------------------------------------------------------------- |
| Compute (Container Apps)        | Rs 0-100             | Scale-to-zero; charges only when answering requests                 |
| Storage (Cosmos DB)             | Rs 0                 | Free tier covers 1000 RU/s + 25 GB                                  |
| Hosting (Static Web Apps)       | Rs 0                 | Free tier; eastasia region for Free-tier availability               |
| Image registry (GHCR)           | Rs 0                 | Free for public packages                                            |
| Secrets (Key Vault)             | ~Rs 50               | Per-secret-operation pricing; very low for this workload            |
| Observability (Log Analytics)   | Rs 50-100            | 1 GB/day daily cap configured                                       |
| Telemetry (App Insights)        | Rs 0                 | Sampled into the same Log Analytics workspace                       |
| LLM (Gemini)                    | Rs 0                 | Free tier: ~1500 req/day, ~15 req/min                               |
| Bot protection (Turnstile)      | Rs 0                 | Free, no usage tier                                                 |
| Domain                          | Rs 0                 | Using free `.azurestaticapps.net` subdomain                         |
| CI/CD (GitHub Actions)          | Rs 0                 | Public repo                                                         |
| Source control (GitHub)         | Rs 0                 | Public repo                                                         |
| Uptime monitoring (UptimeRobot) | Rs 0                 | Free 5-minute pings (currently unused — scale-to-zero is preferred) |
| **Total expected**              | **Rs 100-250/month** |                                                                     |
| **Headroom against budget**     | **Rs 250-400/month** |                                                                     |

---

## Detailed assumptions

### Compute — Azure Container Apps

Pricing model: pay for vCPU-seconds and memory-GB-seconds when active, plus per-million requests.

- **Allocation:** 0.5 vCPU, 1.0 GB memory
- **Active time:** Assumed 10 minutes/day of active compute. Cold start is ~10s; each request takes ~10s for a real LLM call (mostly waiting on Gemini). At 5 unique IPs/day × ~3 questions each = 15 queries × 10s = 2.5 minutes of vCPU-seconds. Plus warm-period overhead.
- **Calculation:** 0.5 vCPU × 600 seconds/day × Rs 0.000034 per vCPU-second = ~Rs 0.30/day = ~Rs 9/month
- **Plus per-request:** First 2M requests/month free; well under that.

Even with optimistic traffic this is well under Rs 100/month. The dominant cost variable is the Gemini free tier (which is free), not Container Apps compute.

### Storage — Azure Cosmos DB

Free tier per Azure account: 1000 RU/s provisioned + 25 GB storage. The project uses ~50 MB total (rate limits expire in 48h, query logs in 90d).

- **Per query RU spend:** ~6-8 RU (one rate-limit read, two cache reads, one log write, one counter increment)
- **Free tier budget:** 1000 RU/s × 60 = 60,000 RU/min = 86 million RU/day
- **Used:** ~150 queries/day × 8 RU = 1,200 RU/day. **0.001% of free tier.**

No realistic traffic scenario would push this above the free tier on a portfolio project.

### Hosting — Azure Static Web Apps (Free tier)

Free tier limits per Azure account:

- 100 GB bandwidth/month
- 2 staging environments per app
- Custom domain support

The frontend bundle is ~400 KB. At 10,000 demo loads/month × 400 KB = 4 GB bandwidth. 4% of the free tier.

**Region note:** Free-tier SWA is only available in select regions. Central India isn't one. We deploy SWA to `eastasia` (Singapore) and route through the same Backend Linking to our centralindia Container App. Adds ~150ms of latency on every request, acceptable for a demo.

### Image registry — GitHub Container Registry

GHCR is free for public packages. The image is ~530 MB (corpus + ChromaDB index baked in).

Storage is unlimited for public repos. Egress is unlimited from GHCR to anonymous pulls (which is what Container Apps does).

If the image were private, GHCR would charge for storage above 500 MB and egress above 1 GB/month from authenticated pulls. Public sidesteps both.

### Secrets — Azure Key Vault

Pricing: ~Rs 0.025 per 10,000 transactions, plus Rs 60/key-version/month for certs (we don't use certs).

We have 6 secrets, each accessed once per Container App revision creation (about once per deploy). That's <100 transactions/month. Cost: effectively zero per the per-transaction line, but Key Vault has a minimum charge of ~Rs 50/month for any non-empty vault.

### Observability — Log Analytics

Log Analytics charges per GB ingested. We have a 1 GB/day cap configured (see `infra/modules/log-analytics.bicep`).

Realistic ingestion: ~1-5 MB/day under normal traffic. Most of the volume is the Cosmos SDK's verbose INFO logging which we should quiet down (see "Known issues" in the README).

Cost: ~Rs 2-3/GB ingested → Rs 50-100/month covers any realistic scenario.

### LLM — Google Gemini free tier

Free tier limits as of June 2026:

- `gemini-2.5-flash-lite`: 15 requests/minute, ~1500 requests/day, ~1M tokens/minute
- `gemini-embedding-001`: similar limits

Each query uses:

- 1 embedding call (for retrieval)
- 1 generation call

At 150 queries/day, we use ~300 Gemini calls/day. 20% of the daily request budget. Token usage is well under the per-minute limit.

The eval harness adds:

- 59 queries + 44 judge calls = 103 calls per full run
- At 15 req/min, ~7 minutes of theoretical Gemini time per eval
- Concurrent eval + judge can hit rate limits → harness retries with 8s backoff

If demand grows beyond demo scale:

- Upgrade to paid tier: ~$0.075 per 1M input tokens, ~$0.30 per 1M output tokens
- At 5K queries/month, paid tier cost: ~$10/month ≈ Rs 840/month (out of demo budget but reasonable for real usage)

---

## What grows with traffic

Three things scale with traffic:

### 1. Container Apps vCPU-seconds

Each request consumes ~5 seconds of vCPU time. The first 10,000 requests/month are within the cost-effective range (under Rs 100/month). Beyond that, scale-to-zero becomes less effective — the container is always warm — and pricing transitions toward "always-on small VM" territory.

**Mitigation:** Set Container Apps' max replicas to 1 in `infra/modules/container-apps.bicep`. Horizontal scaling is unnecessary for a demo, and capping it prevents accidental scale-out cost spikes.

### 2. Cosmos RU/s

The free tier of 1000 RU/s is sufficient for ~125 queries/second. Demo-scale traffic is fine. If real production traffic emerged, we'd transition to paid Cosmos (cheapest tier is ~Rs 1500/month for 400 provisioned RU/s, less than the free tier).

**Practical limit at free tier:** ~10 million queries/month. We will not approach this.

### 3. Log Analytics ingestion

Each query writes ~5 KB of structured logs (request lifecycle + Cosmos SDK noise + retrieval logs). At 5K queries/month, that's 25 MB of ingestion. Free tier covers up to 5 GB/month.

If the Cosmos SDK INFO logging is left noisy (currently we haven't quieted it), each query logs ~50 KB instead of 5 KB. The daily cap of 1 GB/day saves us from a runaway log bill, but ingestion will silently drop after the cap is hit — losing observability for the rest of the day.

**Fix:** A one-line change in `backend/app/main.py` to set `logging.getLogger("azure.cosmos").setLevel(logging.WARNING)`. Reduces log volume by ~90%. Pending.

---

## Kill switches (what happens at budget cap)

The infra includes a monthly budget alert at Rs 500 with notifications at 50% / 75% / 90% / 100% via email (`sarthak_dixit@outlook.com`).

At 100% of budget, the runbook (documented in [`infra/manual-kill-switch.md`](../infra/manual-kill-switch.md)) is:

1. Email arrives from Azure Cost Management
2. Scale the Container App down to 0 replicas:
   ```bash
   az containerapp update --name ca-yzqu7nbhph22c --resource-group rg-robberyrag-dev --min-replicas 0 --max-replicas 0
   ```
3. The frontend will show a "demo at capacity" panel (the backend returns 503 `demo_at_capacity` when the global cap is hit, but with the container scaled to 0 the frontend gets connection refused — handle the disconnect more gracefully in a future iteration)

Manual kill-switch is acceptable for a portfolio project. The earlier design considered an Azure Automation runbook for automatic scale-to-zero on budget hit; that was descoped in Batch 7.3 to keep complexity manageable.

---

## Costs explicitly NOT incurred

To make explicit what we're NOT paying for:

- **Domain registration:** Using free `*.azurestaticapps.net` subdomain. A `.com` would be Rs 800-2000/year if branded.
- **Azure DNS / Private DNS:** Free public DNS via the SWA subdomain. No private DNS needed (no VNet-bound resources).
- **VNet / NAT Gateway / Application Gateway:** None used. Container Apps' default ingress (public, HTTPS) is enough.
- **Storage Account:** None. Cosmos handles all persistent state; ChromaDB index ships in the Docker image.
- **Service Bus / Event Grid:** No async pipelines.
- **Azure Front Door / CDN:** SWA includes CDN. No additional CDN needed.

These choices each save Rs 100-2000/month. The cumulative effect is the project running on what's effectively rounding error.

---

## What it would cost at production scale

For reference, if this system needed to scale to ~10,000 unique users/month making ~50K queries/month:

| Component                                           | Estimated monthly cost |
| --------------------------------------------------- | ---------------------- |
| Container Apps (always-on, B2 equivalent)           | Rs 2000                |
| Cosmos DB paid tier (400 RU/s)                      | Rs 1500                |
| SWA Standard tier (custom domain + backend linking) | Rs 750                 |
| Key Vault (more secrets, more rotation)             | Rs 200                 |
| Log Analytics (no daily cap)                        | Rs 1500                |
| App Insights                                        | Rs 800                 |
| Gemini paid tier (~50K queries × small payload)     | Rs 800                 |
| ACR Basic (private images)                          | Rs 420                 |
| Azure Front Door (CDN + WAF)                        | Rs 1500                |
| Domain (.com + DNS)                                 | Rs 100                 |
| **Total at production scale**                       | **~Rs 9,500/month**    |

That's still cheap for a real product. The portfolio-scale of Rs 250/month is a 38× reduction, achieved by:

1. Free LLM tier (saves Rs 3-5K/month at portfolio volumes)
2. Public GHCR vs private ACR (Rs 420/month)
3. SWA Free vs Standard (Rs 750/month)
4. Scale-to-zero Container Apps vs always-on (Rs 2000/month)
5. Free-tier Cosmos vs paid (Rs 1500/month)

Each is a deliberate engineering decision documented in [`design-decisions.md`](design-decisions.md).
