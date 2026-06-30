# Post-Deploy Checklist

After running `./infra/deploy.sh all` (or `init` + `secrets`), step through this list to confirm everything is wired up.

This list assumes a fresh deploy — for re-deploys, only the items marked **[ALWAYS]** matter; the rest you can skip.

---

## 1. Resource group + 13 resources exist **[ALWAYS]**

```bash
az resource list --resource-group "$RG" --query "[].{Name:name, Type:type}" -o table
```

Expected 12 resources from Bicep + 1 budget (visible via separate command). Names will match these patterns (the `yzqu7nbhph22c` suffix is derived from your RG ID — yours will differ if you change the RG name):

- `robberyrag-cosmos-yzqu7nbhph22c` — Cosmos DB account
- `robberyrag-cosmos-yzqu7nbhph22c/robbery-rag` — Cosmos DB SQL database
- `robberyrag-cosmos-yzqu7nbhph22c/robbery-rag/documents` — Cosmos container
- `kv-yzqu7nbhph22c` — Key Vault
- `robberyrag-law-yzqu7nbhph22c` — Log Analytics workspace
- `robberyrag-appi-yzqu7nbhph22c` — App Insights component
- `robberyrag-backend-mi` — backend's user-assigned managed identity
- `robberyrag-cae-yzqu7nbhph22c` — Container Apps managed environment
- `ca-yzqu7nbhph22c` — Container App
- `robberyrag-swa-yzqu7nbhph22c` — Static Web App

The budget shows up via:

```bash
az consumption budget show \
    --budget-name robberyrag-monthly-budget \
    --resource-group "$RG" \
    --query "{amount:amount, notificationCount:length(values(notifications))}" \
    -o table
```

Expected: amount 500, 4 notifications.

## 2. Key Vault has 6 secrets with real values **[ALWAYS]**

```bash
az keyvault secret list \
    --vault-name kv-yzqu7nbhph22c \
    --query "[].name" \
    -o table
```

Expected 6 names: `admin-password`, `appinsights-connection-string`, `cosmos-connection-string`, `gemini-api-key`, `ip-hash-salt`, `turnstile-secret-key`.

To confirm the values aren't the placeholder, sample one:

```bash
az keyvault secret show \
    --vault-name kv-yzqu7nbhph22c \
    --name ip-hash-salt \
    --query "value" \
    -o tsv | head -c 20
# Should print a hex string starting like "a3b9f24d..." — NOT "placeholder-will-be-replaced..."
```

## 3. Container App is running the right image **[ALWAYS]**

```bash
az containerapp show \
    --name ca-yzqu7nbhph22c \
    --resource-group "$RG" \
    --query "{image:properties.template.containers[0].image, latestRevision:properties.latestRevisionName, runningStatus:properties.runningStatus}" \
    -o table
```

After init: image will be `mcr.microsoft.com/azuredocs/aci-helloworld` (placeholder, listens on port 80, not 8000 — health checks fail, that's fine).

After `./deploy.sh image ghcr.io/sarthakdixit/indian-robbery-rag:latest`: image string updates, new revision provisioning.

## 4. Backend MI can read secrets from Key Vault

Container Apps does this automatically at revision activation. To verify the role assignment is in place:

```bash
az role assignment list \
    --scope "/subscriptions/$(az account show --query id -o tsv)/resourceGroups/$RG/providers/Microsoft.KeyVault/vaults/kv-yzqu7nbhph22c" \
    --query "[].{principal:principalName, role:roleDefinitionName, type:principalType}" \
    -o table
```

Expected two role assignments:

- Your user: `Key Vault Secrets Officer` (User)
- The backend MI: `Key Vault Secrets User` (ServicePrincipal)

## 5. HTTP endpoint responds **[ALWAYS]**

After deploying the real backend image, test:

```bash
BACKEND_FQDN=$(az containerapp show \
    --name ca-yzqu7nbhph22c \
    --resource-group "$RG" \
    --query properties.configuration.ingress.fqdn \
    -o tsv)
curl -sf "https://$BACKEND_FQDN/api/health" | jq .
```

Expected JSON like `{"status": "ok", "corpus_version": "2026.05.14", ...}`.

If it times out: the backend container is still provisioning. Wait ~30 seconds (cold-start, scale-from-zero) and retry.

If it returns 502: the container is restart-looping. Check logs:

```bash
az containerapp logs show \
    --name ca-yzqu7nbhph22c \
    --resource-group "$RG" \
    --tail 50
```

Most common cause on first deploy: an env var is missing or a secret value is wrong.

## 6. CORS allows the SWA URL

The frontend will be hosted on the SWA URL. Verify the backend's CORS allowlist includes it:

```bash
SWA_URL=$(az staticwebapp show \
    --name robberyrag-swa-yzqu7nbhph22c \
    --resource-group "$RG" \
    --query "defaultHostname" \
    -o tsv)

curl -sf "https://$BACKEND_FQDN/api/health" \
    -H "Origin: https://$SWA_URL" \
    -I | grep -i access-control
```

Expected response header: `access-control-allow-origin: https://<swa-hostname>` (no trailing slash).

If absent or set to a different origin: the `CORS_ALLOWED_ORIGINS` env var on the Container App is wrong. Check via:

```bash
az containerapp show \
    --name ca-yzqu7nbhph22c \
    --resource-group "$RG" \
    --query "properties.template.containers[0].env[?name=='CORS_ALLOWED_ORIGINS'].value | [0]" \
    -o tsv
```

## 7. Cosmos can be reached from the Container App

This will be fully verified when a real query hits the backend. For now, confirm the connection string in Key Vault is reachable:

```bash
COSMOS_CONN=$(az keyvault secret show \
    --vault-name kv-yzqu7nbhph22c \
    --name cosmos-connection-string \
    --query value \
    -o tsv)
[[ "$COSMOS_CONN" == AccountEndpoint=* ]] && echo "OK: well-formed" || echo "FAIL: malformed"
```

## 8. Budget alert email received

Azure sends a confirmation email when a budget is created. Within ~15 min of the deploy, you should receive:

- Subject: usually contains "Cost Management" and the budget name
- From: `azure-noreply@microsoft.com`

If after an hour you've received nothing, check:

- Spam folder
- The email in the budget config matches yours (`az consumption budget show ... --query notifications`)

If still nothing: the alert pipeline is broken but won't fix itself without Microsoft support. The 50/75/90/100% emails will be in similar trouble. For a portfolio demo, this is annoying but not blocking.

## 9. Static Web App is hosted (even with no content)

```bash
curl -sI "https://$SWA_URL" | head -3
```

Expected `HTTP/2 200` (or 404 if no content uploaded yet — the SWA is provisioned but empty). Either is fine post-init; frontend deploy is a separate step.

## 10. GitHub Actions can deploy

This isn't tested by the deploy script — it's tested by pushing a commit to `main` and watching the workflow run. See `infra/azure-oidc-setup.md` for the federation setup.

---

## Quick smoke test (single command)

After `./deploy.sh all`, run:

```bash
./infra/deploy.sh status
```

Then for the live backend (assuming real image is deployed):

```bash
curl -sf "https://$(az containerapp show -n ca-yzqu7nbhph22c -g $RG --query properties.configuration.ingress.fqdn -o tsv)/api/health"
```

200 + valid JSON = system is working end-to-end.
