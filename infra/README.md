# `infra/` — Azure Infrastructure

This folder owns the Azure infrastructure for indian-robbery-rag. The deployment target is a single resource group (`rg-robberyrag-dev` by default) containing the full stack: Cosmos DB serverless, Key Vault, Log Analytics + App Insights, a Container App for the FastAPI backend, a Static Web App for the React frontend, plus a monthly budget with email alerts.

The Bicep modules are declarative and idempotent. The `.sh` scripts wrap the imperative steps (seeding placeholder secrets, populating real secret values from env vars, fetching connection strings, restarting Container Apps) that Bicep can't do.

---

## Quick start

```bash
# 1. Login and select the right subscription
az login
az account set --subscription <subscription-id>

# 2. Provide values for the user-supplied secrets
export GEMINI_API_KEY='AIza...'        # from https://aistudio.google.com/apikey
export ADMIN_PASSWORD='use-a-strong-password-here'
export TURNSTILE_SECRET_KEY='0x4A...'  # from Cloudflare Turnstile dashboard

# 3. From the repo root, run a full deploy
./infra/deploy.sh all

# 4. After CI has built and pushed the backend image, update the Container App
./infra/deploy.sh image ghcr.io/sarthakdixit/indian-robbery-rag:latest

# 5. Verify end-to-end
./infra/deploy.sh status
cat infra/post-deploy-checklist.md
```

---

## What's in this folder

### Bicep (declarative infrastructure)

| File                           | Role                                                                                                                                                                 |
| ------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `main.bicep`                   | Top-level orchestrator. RG-scoped. Calls every module below in DAG order.                                                                                            |
| `parameters.json`              | Default parameter values (location, resource prefix, environment).                                                                                                   |
| `modules/cosmos.bicep`         | Cosmos DB serverless account + database + container. Partition key `/pk`, TTL enabled.                                                                               |
| `modules/key-vault.bicep`      | Key Vault (Standard, RBAC, soft-delete 7 days, no purge protection). Includes role assignments for the deployer (Secrets Officer) and the backend MI (Secrets User). |
| `modules/log-analytics.bicep`  | Log Analytics workspace + workspace-based App Insights. 1 GB/day cap, 30-day retention.                                                                              |
| `modules/container-apps.bicep` | Managed environment + Container App. Wires Key Vault secret refs to env vars.                                                                                        |
| `modules/static-web-app.bicep` | Static Web App Free. Hosted in eastasia (Free not available in centralindia).                                                                                        |
| `modules/budget-alerts.bicep`  | ₹500/month budget with 4 notifications (50/75% Forecasted, 90/100% Actual).                                                                                          |

### Scripts (imperative orchestration)

| File          | Role                                                                           |
| ------------- | ------------------------------------------------------------------------------ |
| `deploy.sh`   | Subcommand-style: `init`, `secrets`, `image`, `all`, `status`, `help`.         |
| `teardown.sh` | Destroys the resource group. Two interactive prompts. Optional `--purge` flag. |

### Documentation

| File                       | Role                                                                                     |
| -------------------------- | ---------------------------------------------------------------------------------------- |
| `README.md`                | This file.                                                                               |
| `azure-oidc-setup.md`      | One-time setup: federate GitHub Actions to Azure AD (no stored secrets).                 |
| `manual-kill-switch.md`    | Emergency-stop operator playbook (replaces the auto-stop runbook we chose not to build). |
| `post-deploy-checklist.md` | Step-by-step verification after a fresh deploy.                                          |

---

## Architecture decisions worth knowing

These show up in the Bicep and scripts but the rationale isn't obvious from reading them.

**Cosmos serverless, not free-tier-provisioned.** The free tier allows one account per subscription, and ours is already used elsewhere. Serverless costs nothing at idle and roughly ₹5-10/month at portfolio scale. The trade-off vs autoscale provisioned: no minimum throughput charges, but no SLA-guaranteed RU/s either. Acceptable for a demo.

**Static Web App Free tier with no linked backend.** The Standard tier supports "linked backends" (proxying `/api/*` to a Container App), which would simplify CORS and avoid exposing the Container App's URL publicly. But Standard is ~₹750/month vs Free's ₹0. The React frontend talks directly to the Container App's public ingress, with CORS allowlisting the SWA URL. Acceptable for a demo.

**GitHub Container Registry (GHCR) instead of Azure Container Registry.** ACR Basic is ~₹420/month. GHCR public images are free and Container Apps can pull them without auth. The trade-off: vendor mixing. Acceptable for a portfolio.

**User-assigned managed identity, not system-assigned.** System-assigned creates a chicken-and-egg with Key Vault secret references: the Container App needs to exist to create the MI, but the MI needs Key Vault access before the Container App starts. User-assigned MIs can be created independently and granted RBAC before the Container App ever exists. The cost is one more resource.

**Container App image placeholder = `mcr.microsoft.com/azuredocs/aci-helloworld`.** This is a public Microsoft sample. It listens on port 80, not 8000, so the Container App's health probes will fail with the placeholder — but the resource gets created cleanly, and the deploy script replaces it via `./deploy.sh image <tag>` once CI has pushed the real image.

**Six secrets seeded as placeholders before the first Bicep deploy.** Azure Container Apps validates the existence of every secret referenced via `keyVaultUrl` at create-time, even though the values are only read at first request. Without seeded placeholders, the first deploy of a fresh stack fails at the Container App step. `deploy.sh init` handles this automatically — see the recovery flow in the script.

**No Azure Automation runbook for auto-stop at 100% budget.** design.md called for one (AP-7); we chose the manual path (`manual-kill-switch.md`). Rationale: portfolio-scale traffic burns paise per minute even when stuck on, so a human-response delay of hours is acceptable. PowerShell runbooks add operational complexity (managed identity, role assignments, webhook URLs) that's hard to justify for the threat model. Documented explicitly so the design choice isn't accidentally reversed later.

**Container Apps scale-to-zero (`min-replicas: 0`, `max-replicas: 1`).** First-request cold start is ~10-20 seconds. Tolerable for a demo. The frontend shows a "warming up the legal research engine" message during this window — see `frontend/src/components/states/ColdStartLoader.tsx`.

**No `dependsOn` chains in main.bicep beyond what Bicep infers from `outputs`.** Bicep's DAG resolver figures out dependency order from output references. Explicit `dependsOn` is a smell — usually a sign that something else is wrong (e.g., wrong module structure). The exception: the conditional KV role assignment for the backend MI, which is declared inside `key-vault.bicep` rather than `main.bicep` because role-assignment scopes must be resolvable at planning time (BCP120).

---

## Costs (idle)

At idle the entire stack costs effectively ₹0/month:

| Resource              | Idle cost        | At low traffic                   |
| --------------------- | ---------------- | -------------------------------- |
| Cosmos serverless     | ~₹0              | ~₹5-10                           |
| Key Vault             | ~₹0              | ~₹0                              |
| Log Analytics         | ~₹0              | ~₹0 (5 GB/month free)            |
| App Insights          | ~₹0              | ~₹0 (workspace-based, free tier) |
| Container Apps        | ~₹0 (scale-to-0) | ~₹50-150                         |
| Static Web App Free   | ₹0               | ₹0                               |
| GHCR (image registry) | ₹0               | ₹0 (public)                      |

Total worst case: ~₹200/month, well under the ₹500 budget.

---

## Common operations

### Update secret values

```bash
export GEMINI_API_KEY='new-value'
./infra/deploy.sh secrets
```

The script preserves the IP hash salt (rotating it would break all existing rate-limit hashes). Other secrets are overwritten.

### Update the backend image after CI builds

```bash
./infra/deploy.sh image ghcr.io/sarthakdixit/indian-robbery-rag:sha-abc1234
```

### Roll back to a previous revision

```bash
# List revisions
az containerapp revision list \
    --name ca-yzqu7nbhph22c \
    --resource-group "$RG" \
    --query "[].{name:name, image:properties.template.containers[0].image, created:properties.createdTime}" \
    -o table

# Activate an older one
az containerapp revision activate \
    --name ca-yzqu7nbhph22c \
    --resource-group "$RG" \
    --revision <revision-name>
```

### See current Container App logs

```bash
az containerapp logs show \
    --name ca-yzqu7nbhph22c \
    --resource-group "$RG" \
    --tail 100 --follow
```

### Emergency stop (cost runaway)

See `manual-kill-switch.md`. Fastest path:

```bash
az containerapp update \
    --name ca-yzqu7nbhph22c \
    --resource-group rg-robberyrag-dev \
    --min-replicas 0 --max-replicas 0
```

This stops the meter immediately. Revert with `--max-replicas 1` later.

### Full teardown

```bash
./infra/teardown.sh --purge
```

Two confirmation prompts. The `--purge` flag also purges the soft-deleted Key Vault (frees the name for immediate reuse).

---

## Re-deploying from scratch

```bash
./infra/teardown.sh --purge
# Wait for delete to finish (script polls for ~minutes)

./infra/deploy.sh all
./infra/deploy.sh image ghcr.io/sarthakdixit/indian-robbery-rag:latest
```

Cosmos account names are soft-deleted for 90 days even after RG delete. If you teardown and re-deploy within 90 days, the Cosmos account name `robberyrag-cosmos-<suffix>` will be unavailable. Two options:

1. Wait 90 days.
2. Change the resource group name — the `<suffix>` is derived from `uniqueString(resourceGroup().id)`, so a different RG name yields different resource names.

---

## When to update this README

- A new module is added under `modules/`
- The architecture decisions in the "Architecture decisions worth knowing" section change
- A new common operation is worth documenting
- Costs at idle vs traffic change materially

If you edit the Bicep, update the table under "What's in this folder" too.
