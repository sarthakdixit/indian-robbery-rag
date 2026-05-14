# Azure OIDC Federation Setup

> **One-time manual setup.** Do this once before running the `backend-deploy` and `frontend-deploy` GitHub Actions workflows. Estimated time: 20-30 minutes.

## What This Solves

GitHub Actions needs to authenticate to Azure to deploy. The old way uses long-lived service principal secrets stored in GitHub. The modern way — **OpenID Connect (OIDC) federation** — exchanges a short-lived GitHub token for an Azure access token at deploy time. No secrets stored anywhere.

This is the pattern production teams use. It's also worth a sentence in interviews: _"I configured OIDC federation between GitHub and Azure so deploys use short-lived tokens instead of long-lived service principal secrets."_

## Prerequisites

- An Azure subscription (free tier is fine)
- Azure CLI installed locally (`az --version`)
- Owner or User Access Administrator role on the subscription (needed to create role assignments)
- This repository created on GitHub
- A resource group created in Azure (will provision in Batch 7; for OIDC setup alone, any RG works)

## Step 1: Create an Azure AD application

```bash
az ad app create --display-name "github-indian-robbery-rag"
```

Note the `appId` from the output — this is your `AZURE_CLIENT_ID`.

## Step 2: Create a service principal for the app

```bash
APP_ID="<paste appId from step 1>"
az ad sp create --id "$APP_ID"
```

## Step 3: Grant the service principal the necessary roles

You need three role assignments. Replace `<SUBSCRIPTION_ID>` and `<RESOURCE_GROUP>` with your values.

```bash
SUBSCRIPTION_ID="<your subscription id>"
RG="<your resource group, e.g. rg-indian-robbery-rag>"

# Contributor on the resource group — for Container Apps revision updates
az role assignment create \
  --role "Contributor" \
  --assignee "$APP_ID" \
  --scope "/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RG"

# AcrPush on Container Registry — for pushing images
# (Run this after Batch 7 provisions the ACR. Until then, skip.)
ACR_NAME="<your container registry name>"
az role assignment create \
  --role "AcrPush" \
  --assignee "$APP_ID" \
  --scope "/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RG/providers/Microsoft.ContainerRegistry/registries/$ACR_NAME"
```

For least-privilege, prefer narrowing `Contributor` to specific resource-type roles (`Container Apps Contributor`, `Key Vault Secrets User`, etc.) once you know the exact resources. See [`infra/`](.) once Batch 7 lands.

## Step 4: Create federated credentials

This is the part that says "trust GitHub Actions to act as this service principal, but only for specific workflows in specific repos."

Create a JSON file `federated-credential-main.json`:

```json
{
  "name": "github-main-branch",
  "issuer": "https://token.actions.githubusercontent.com",
  "subject": "repo:<YOUR_GH_ORG>/<YOUR_REPO_NAME>:ref:refs/heads/main",
  "description": "GitHub Actions deploys from main branch",
  "audiences": ["api://AzureADTokenExchange"]
}
```

Apply it:

```bash
az ad app federated-credential create \
  --id "$APP_ID" \
  --parameters @federated-credential-main.json
```

If you also want pull-request workflows to authenticate (e.g., for preview deployments), create a second credential with `subject: "repo:<ORG>/<REPO>:pull_request"`.

For the production environment specifically (which the deploy workflow targets via `environment: production`), use:

```json
{
  "name": "github-production-env",
  "issuer": "https://token.actions.githubusercontent.com",
  "subject": "repo:<YOUR_GH_ORG>/<YOUR_REPO_NAME>:environment:production",
  "description": "GitHub Actions deploys to production environment",
  "audiences": ["api://AzureADTokenExchange"]
}
```

## Step 5: Get the tenant ID

```bash
az account show --query tenantId -o tsv
```

This is your `AZURE_TENANT_ID`.

## Step 6: Add GitHub repository variables

In your GitHub repo: **Settings → Secrets and variables → Actions → Variables tab → New repository variable**.

Add the following as **variables** (not secrets — these are not sensitive):

| Variable name               | Value                                                             |
| --------------------------- | ----------------------------------------------------------------- |
| `AZURE_CLIENT_ID`           | The `appId` from Step 1                                           |
| `AZURE_TENANT_ID`           | From Step 5                                                       |
| `AZURE_SUBSCRIPTION_ID`     | Your subscription id                                              |
| `AZURE_RESOURCE_GROUP`      | Your resource group name                                          |
| `AZURE_CONTAINER_REGISTRY`  | Your ACR name (without `.azurecr.io`) — fill in after Batch 7     |
| `AZURE_CONTAINER_APP_NAME`  | Your Container App name — fill in after Batch 7                   |
| `AZURE_STATIC_WEB_APP_NAME` | Your SWA name — fill in after Batch 7                             |
| `BACKEND_HEALTH_URL`        | `https://<container-app-fqdn>/api/health` — fill in after Batch 7 |

The deploy workflow's "Check whether deploy is ready" step lists exactly what's missing, so partial setup is fine — the workflow gracefully no-ops until everything is set.

## Step 7: Create the production environment in GitHub

In your repo: **Settings → Environments → New environment** → name it `production`.

Optionally add protection rules (required reviewers, wait timer). For a portfolio project, no protection rules is fine — the federated credential restricts who can deploy.

## Verifying Setup

After everything is configured and Batch 7 has provisioned resources, push a small change to `backend/` or trigger the workflow manually:

```bash
gh workflow run backend-deploy
```

The workflow should:

1. Log in to Azure via OIDC (no secret prompts)
2. Push a new image to ACR
3. Update the Container App revision
4. Smoke-test the health endpoint

If the OIDC login fails with `AADSTS70021` or similar, check:

- The `subject` in your federated credential exactly matches the workflow's `ref` (e.g., `refs/heads/main`, not `refs/heads/master`)
- The repo name in the `subject` is correct (case-sensitive)
- The `production` environment exists in GitHub if your credential targets `environment:production`

## Cleanup / Rotation

To remove a federated credential:

```bash
az ad app federated-credential list --id "$APP_ID"
az ad app federated-credential delete --id "$APP_ID" --federated-credential-id "<credential id>"
```

To rotate the service principal entirely, delete the AD app:

```bash
az ad app delete --id "$APP_ID"
```

Then redo Steps 1-6 with a fresh app.

## References

- [Azure docs: Configure an app to trust a GitHub repo](https://learn.microsoft.com/azure/active-directory/workload-identities/workload-identity-federation-create-trust)
- [GitHub docs: Configuring OpenID Connect in Azure](https://docs.github.com/actions/deployment/security-hardening-your-deployments/configuring-openid-connect-in-azure)
- [`azure/login@v2` action](https://github.com/Azure/login)
