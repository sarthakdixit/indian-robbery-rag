# Manual Kill Switch

> When to use this: budget alerts indicate spending has reached or exceeded the monthly cap, and you want to **stop the meter** without tearing down resources.

This document is the recovery path for design.md AP-7. The original spec called for an auto-stop Azure Automation runbook; we chose to implement the manual path instead. Rationale: the demo's traffic is low enough that the lag between cost spike and human response (hours) is acceptable, and Automation runbooks add operational complexity (managed identity setup, PowerShell debugging, webhook URLs) that's hard to justify for a portfolio demo's threat model.

The Azure budget (`infra/modules/budget-alerts.bicep`) sends email alerts at 50% Forecasted, 75% Forecasted, 90% Actual, and 100% Actual of the ₹500/month cap. When you see the 90% or 100% email, follow this playbook.

---

## Quick reference

```bash
RG=rg-robberyrag-dev
CONTAINER_APP=ca-yzqu7nbhph22c   # actual name from `az containerapp list -g $RG -o table`
```

| Action                                      | Command                                                                                                                                                                                                  | Time          | Cost impact                                                                         |
| ------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------- | ----------------------------------------------------------------------------------- | ------------------------------------------- |
| Stop Container App (recommended first step) | `az containerapp update --name $CONTAINER_APP --resource-group $RG --min-replicas 0 --max-replicas 0`                                                                                                    | ~30s          | Stops compute meter immediately                                                     |
| Restart Container App                       | `az containerapp update --name $CONTAINER_APP --resource-group $RG --min-replicas 0 --max-replicas 1`                                                                                                    | ~30s          | Resumes scale-to-zero behaviour                                                     |
| Stop and delete revisions (more aggressive) | `az containerapp revision deactivate --name $CONTAINER_APP --resource-group $RG --revision $(az containerapp revision list --name $CONTAINER_APP --resource-group $RG --query "[?properties.active].name | [0]" -o tsv)` | ~30s                                                                                | Same as above but disables current revision |
| Nuclear option (delete whole RG)            | `az group delete --name $RG --yes --no-wait`                                                                                                                                                             | minutes       | All resources deleted; soft-deleted Cosmos + Key Vault names locked for 90 / 7 days |

---

## Step-by-step: respond to a 90% or 100% alert

### 1. Identify the cost source

Don't shut anything down before knowing what's burning money. At our portfolio scale, the only resources that bill per-second are Container Apps. Cosmos serverless, Key Vault, Log Analytics free tier, App Insights free tier, and Static Web Apps Free are all functionally ₹0 idle and shouldn't be the cause.

```bash
# Show cost breakdown by service for current month
az consumption usage list \
    --start-date "$(date -d 'first day of this month' '+%Y-%m-%d')" \
    --end-date "$(date '+%Y-%m-%d')" \
    --query "[?contains(instanceName, 'robberyrag') || contains(instanceName, 'ca-yzqu7nbhph22c') || contains(instanceName, 'kv-yzqu7nbhph22c')].{Service:meterName, Resource:instanceName, Cost:pretaxCost}" \
    -o table
```

If `az consumption usage list` is unavailable on your subscription tier, use the Cost Management blade in the Azure portal: **Subscriptions → rg-robberyrag-dev → Cost analysis**.

Most likely culprit on a portfolio demo: a misconfigured Container App that's stuck scaled-up (e.g., a max-replicas=10 set by mistake), or a runaway log ingestion blowing past the Log Analytics 5 GB free tier into paid tier.

### 2. Stop the Container App

The cheapest and most reversible fix:

```bash
az containerapp update \
    --name "$CONTAINER_APP" \
    --resource-group "$RG" \
    --min-replicas 0 \
    --max-replicas 0
```

This sets both min and max replicas to zero. The Container App resource remains; the meter stops. No request will be served. Verify with:

```bash
az containerapp show \
    --name "$CONTAINER_APP" \
    --resource-group "$RG" \
    --query "{minReplicas:properties.template.scale.minReplicas, maxReplicas:properties.template.scale.maxReplicas, latestRevision:properties.latestRevisionName}" \
    -o table
```

Both replica counts should show as `0`.

### 3. If costs are coming from somewhere else

**Log Analytics ingestion exceeding 5 GB free tier:**

```bash
# Check current ingestion volume
az monitor log-analytics workspace show \
    --resource-group "$RG" \
    --workspace-name robberyrag-law-yzqu7nbhph22c \
    --query "{dailyQuotaGb:workspaceCapping.dailyQuotaGb, retentionInDays:retentionInDays}" \
    -o table

# Lower the daily cap aggressively (e.g., 0.1 GB/day) to stop ingestion
az monitor log-analytics workspace update \
    --resource-group "$RG" \
    --workspace-name robberyrag-law-yzqu7nbhph22c \
    --workspace-daily-quota-gb 0.1
```

The Bicep already sets `dailyQuotaGb: 1`. If the workspace is somehow ingesting more than 1 GB/day, something is misconfigured and logs are likely leaking from another resource group.

**Cosmos beyond expected:** unlikely on serverless without traffic, but verify with:

```bash
az cosmosdb show \
    --name robberyrag-cosmos-yzqu7nbhph22c \
    --resource-group "$RG" \
    --query "{capacity:capabilities, capacityMode:enableMultipleWriteLocations}" \
    -o table
```

If somehow the account got switched to provisioned throughput, that's a ~$24/month minimum. Switching back to serverless requires deleting and recreating the account (mode change isn't supported in place).

### 4. Wait for the next billing-cycle reset

The budget resets on the first day of each month. Once costs reset, you can re-enable the Container App:

```bash
az containerapp update \
    --name "$CONTAINER_APP" \
    --resource-group "$RG" \
    --min-replicas 0 \
    --max-replicas 1
```

This restores the original scale-to-zero behaviour (0 when idle, up to 1 when traffic arrives).

### 5. Nuclear option (full teardown)

If you want to stop ALL resources and start fresh next month, delete the entire resource group:

```bash
az group delete --name "$RG" --yes --no-wait
```

**Caveats before running this:**

1. **Cosmos account names are soft-deleted for 90 days.** You won't be able to recreate `robberyrag-cosmos-yzqu7nbhph22c` for 90 days after deletion. To preserve the name option, purge after delete:

   ```bash
   # WAIT for the delete to finish first (check `az group show` returns NotFound),
   # then purge the Cosmos account name reservation:
   az cosmosdb restore-list --location centralindia -o table   # confirm the soft-deleted entry exists
   # No CLI to purge Cosmos account names — they auto-expire after 90 days.
   ```

2. **Key Vault names are soft-deleted for 7 days** (our config). Same name-reservation issue. To purge immediately:

   ```bash
   az keyvault purge --name kv-yzqu7nbhph22c
   ```

3. **GitHub Actions OIDC federation** (set up per `infra/azure-oidc-setup.md`) survives RG deletion. No fix needed; just re-deploy and CI works again.

4. **The budget itself doesn't auto-delete with the RG.** Run:
   ```bash
   az consumption budget delete --budget-name robberyrag-monthly-budget --resource-group "$RG"
   ```

### 6. After the dust settles

Re-deploy with the existing Bicep (`infra/main.bicep`) once costs reset or the underlying issue is fixed. The deploy is idempotent — same names will be recreated identically.

---

## How long before the kill switch helps?

Cost data refreshes every 8-24 hours per Azure docs. Budget evaluations run every 24 hours. Emails are sent within an hour of an evaluation. So worst case from a spike to a 100% email: ~25 hours.

This is why the budget has FOUR thresholds, not just 100%. The 50% Forecasted email is the early-warning system: you'll get that one ~24h after costs start trending high, giving you time to investigate before actual spend reaches a serious level.

If you wanted faster detection, the Bicep-out-of-scope path is:

- Add an Application Insights cost-anomaly query running every 5 minutes
- Route to a webhook that scales Container Apps to zero
- Skip the manual step entirely

We didn't build this because portfolio-scale traffic doesn't justify the operational complexity.

---

## Test that the budget alerts actually fire

You can't actually trigger a 50% threshold without spending money, but you CAN confirm the budget is configured correctly:

```bash
az consumption budget show \
    --budget-name robberyrag-monthly-budget \
    --resource-group "$RG" \
    --query "{amount:amount, currentSpend:currentSpend.amount, notifications:notifications}" \
    -o json
```

The `notifications` object should show 4 entries with the right thresholds and your email in `contactEmails`. The `currentSpend` value is updated by Azure every 8-24 hours.

If the email never arrives at the 50% mark of an actual high-spend month, check:

1. Email in spam folder
2. Azure Cost Management portal → Budgets → click into the budget → "Notifications" tab → verify the email is listed and enabled
3. Confirm the budget's `currentSpend.amount` is actually crossing the threshold (sometimes spend is reported in a different currency than you expect)

---

## Why no Automation runbook?

design.md AP-7 originally called for an Azure Automation runbook that auto-scales Container Apps to zero on 100% threshold. We chose the manual path for these reasons:

1. **Threat model**: This is a portfolio demo, not a production SaaS. The cost of a 24-hour delay between "100% reached" and "human responds" is bounded by the resources' burn rate, which at our scale is paise per minute. Maximum exposure on a delayed response is single-digit rupees.

2. **Operational complexity**: Automation runbooks require an Automation Account, a system-assigned managed identity, a Container Apps Contributor role assignment, and PowerShell runbook content. Each adds a failure mode. Budget alert → webhook → runbook → API call has four hop points that can break silently.

3. **Skill area**: PowerShell is outside the team's primary expertise (Python + Bash). A bug in the runbook would compound the cost-runaway problem rather than fix it.

The manual kill switch is the honest design: explicit, simple, reversible.
