# Azure OIDC Federation Setup

> **One-time manual setup.** Do this once before the `backend-deploy` workflow can update the Container App. Estimated time: 15-20 minutes.

## What This Solves

GitHub Actions needs to authenticate to Azure to deploy. The old way uses long-lived service principal secrets stored in GitHub. The modern way — **OpenID Connect (OIDC) federation** — exchanges a short-lived GitHub-issued token for an Azure access token at deploy time. No secrets stored anywhere.

This is what production teams use. In interviews: _"I configured OIDC federation between GitHub and Azure so deploys use short-lived tokens instead of stored credentials."_

## Prerequisites

- Azure CLI logged in (`az account show` returns your subscription)
- Owner or User Access Administrator role on the subscription (needed to create role assignments)
- Repo exists at `https://github.com/sarthakdixit/indian-robbery-rag`
- Resource group `rg-robberyrag-dev` already provisioned (Batch 7.1+)

## What you'll create

- An Azure AD application (one)
- A service principal attached to it (one)
- One role assignment (`Contributor` on `rg-robberyrag-dev`)
- One federated credential (GitHub `environment:production` → this SP)
- A GitHub Actions `production` environment
- 5 GitHub Actions repository variables

## Step 1 — Create the Azure AD application

```bash
az ad app create --display-name "github-indian-robbery-rag"
```

Capture the `appId` from the output — this becomes `AZURE_CLIENT_ID` in GitHub.

```bash
# Store it in a shell var so we don't have to copy/paste repeatedly
APP_ID=$(az ad app list --display-name "github-indian-robbery-rag" --query "[0].appId" -o tsv)
echo "AZURE_CLIENT_ID = $APP_ID"
```

## Step 2 — Create the service principal

```bash
az ad sp create --id "$APP_ID"
```

## Step 3 — Grant Contributor on the resource group

```bash
SUBSCRIPTION_ID=$(az account show --query id -o tsv)
RG=rg-robberyrag-dev

az role assignment create \
    --role "Contributor" \
    --assignee "$APP_ID" \
    --scope "/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RG"
```

`Contributor` on the RG lets the workflow update Container App revisions. We don't need `AcrPush` (no ACR — we use GHCR which doesn't need Azure auth) or any Key Vault role (the Container App's user-assigned MI handles vault reads at runtime; CI doesn't touch the vault).

For tighter least-privilege you could swap `Contributor` for `Container Apps Contributor`, but `Contributor` is what most CI/CD examples use and won't surprise you if you add other resources to the same workflow later.

## Step 4 — Create the federated credential

The workflow deploys to GitHub's `production` environment, so the federation subject must match the `environment:production` form (not the `ref:refs/heads/main` form). When a workflow declares `environment:` GitHub's OIDC token uses the environment subject in the `sub` claim, not the branch ref.

Create `federated-credential.json`:

```bash
cat > /tmp/federated-credential.json << 'EOF'
{
  "name": "github-production-env",
  "issuer": "https://token.actions.githubusercontent.com",
  "subject": "repo:sarthakdixit/indian-robbery-rag:environment:production",
  "description": "GitHub Actions deploys to production environment",
  "audiences": ["api://AzureADTokenExchange"]
}
EOF

az ad app federated-credential create \
    --id "$APP_ID" \
    --parameters @/tmp/federated-credential.json
```

If you later want PR-preview deploys, add a second credential with subject `repo:sarthakdixit/indian-robbery-rag:pull_request`.

## Step 5 — Get the tenant ID

```bash
TENANT_ID=$(az account show --query tenantId -o tsv)
echo "AZURE_TENANT_ID = $TENANT_ID"
```

## Step 6 — Create the production environment in GitHub

In your repo: **Settings → Environments → New environment** → name it `production`.

Optional protection rules (required reviewers, wait timer) — skip for a portfolio project. The federated credential already restricts who can deploy.

## Step 7 — Add GitHub Actions repository variables

In your repo: **Settings → Secrets and variables → Actions → Variables tab → New repository variable**.

These are **variables** (not secrets). They're not sensitive — they're identifiers that anyone reading the workflow YAML can see anyway.

| Variable                   | Value                                  |
| -------------------------- | -------------------------------------- |
| `AZURE_CLIENT_ID`          | The `appId` from Step 1                |
| `AZURE_TENANT_ID`          | From Step 5                            |
| `AZURE_SUBSCRIPTION_ID`    | `0435696f-4caf-4b4e-ac74-35a2d7714c6b` |
| `AZURE_RESOURCE_GROUP`     | `rg-robberyrag-dev`                    |
| `AZURE_CONTAINER_APP_NAME` | `ca-yzqu7nbhph22c`                     |

`BACKEND_HEALTH_URL` is optional — the workflow auto-resolves it from the Container App's ingress FQDN. Set it manually only if you have a custom domain.

The workflow's "Check whether deploy is ready" step lists any missing variables, so partial setup is fine — the workflow gracefully no-ops until everything is set.

## Verifying setup

After everything is configured, push a small change to `backend/` (e.g., a comment in a Python file) or trigger the workflow manually:

```bash
gh workflow run backend-deploy
gh run watch
```

Expected flow:

1. Checkout
2. Pre-flight check — all 5 vars present, Dockerfile exists, ready=true
3. Compute image refs → `ghcr.io/sarthakdixit/indian-robbery-rag:sha-<7chars>` + `:latest`
4. Set up Buildx
5. Log in to GHCR using the built-in `GITHUB_TOKEN` (no PAT needed; the workflow has `packages: write` permission)
6. Build + push image
7. Log in to Azure via OIDC (no secret prompts — federated)
8. `az containerapp update --image ...`
9. Resolve health URL from Container App FQDN
10. Poll `/api/health` until it returns 200

The first build will take ~5 minutes (cold Docker layer cache). Subsequent builds without Dockerfile changes take ~30 seconds (cached layers).

## After first push: make the GHCR package public

By default, GHCR creates new packages as **private**. Container Apps can pull private GHCR packages only with auth configured — which adds complexity we want to skip.

After the first successful workflow run:

1. Go to `https://github.com/sarthakdixit?tab=packages`
2. Click `indian-robbery-rag`
3. **Package settings → Change package visibility → Public**

After that, Container Apps can pull anonymously. The image is publicly readable (anyone can `docker pull ghcr.io/sarthakdixit/indian-robbery-rag:latest`); this is acceptable because the image contains only the FastAPI backend code, which is open-source in this repo anyway. Secrets are NOT baked into the image — they're injected at runtime from Key Vault.

## Troubleshooting

**`AADSTS70021: No matching federated identity record found`**
The `subject` in your federated credential doesn't match the workflow's `sub` claim. Verify:

- The repo name is exactly `sarthakdixit/indian-robbery-rag` (case-sensitive)
- The environment name in the workflow (`environment: production`) matches the credential's `:environment:production` suffix
- The `production` environment actually exists in GitHub Settings → Environments

**`Forbidden: pull access denied` from Container Apps**
The GHCR package is still private. Make it public per the section above.

**`Insufficient privileges to complete the operation`**
The deploying user (you) doesn't have permission to create role assignments. Need Owner or User Access Administrator on the subscription. Get a tenant admin to run Step 3, or ask them to grant you the role.

## Cleanup / rotation

To remove the federated credential:

```bash
az ad app federated-credential list --id "$APP_ID"
az ad app federated-credential delete \
    --id "$APP_ID" \
    --federated-credential-id "<credential id from list>"
```

To rotate the entire SP, delete the AD app and redo Steps 1-7:

```bash
az ad app delete --id "$APP_ID"
```

## References

- [Azure docs: Configure an app to trust a GitHub repo](https://learn.microsoft.com/azure/active-directory/workload-identities/workload-identity-federation-create-trust)
- [GitHub docs: Configuring OpenID Connect in Azure](https://docs.github.com/actions/deployment/security-hardening-your-deployments/configuring-openid-connect-in-azure)
- [`azure/login@v2` action](https://github.com/Azure/login)
- [GHCR docs: Working with the Container registry](https://docs.github.com/packages/working-with-a-github-packages-registry/working-with-the-container-registry)
