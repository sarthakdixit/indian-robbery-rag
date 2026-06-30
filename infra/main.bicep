// main.bicep — top-level orchestrator for the Indian Robbery Law RAG
// project's Azure infrastructure.
//
// SCOPE: Resource Group. Run with:
//   az deployment group create \
//       --resource-group <rg> \
//       --template-file infra/main.bicep \
//       --parameters @infra/parameters.json \
//       --parameters deployerPrincipalId=<your-object-id>
//
// CURRENT STATE (Chunk 7.2): provisions the full data + compute stack.
//   - Cosmos serverless (cosmos.bicep)
//   - Key Vault with RBAC (key-vault.bicep)
//   - Log Analytics + App Insights (log-analytics.bicep)
//   - Static Web App Free (static-web-app.bicep)
//   - User-assigned MI for backend + Key Vault role assignment (here)
//   - Container Apps managed environment + Container App (container-apps.bicep)
//
// Cost protection (budget alerts) arrives in Chunk 7.3. Deploy scripts
// in 7.4 will seed Key Vault secrets and override the backend image
// from the placeholder.
//
// Naming convention: all resources derive their name from
// `resourcePrefix + uniqueString(resourceGroup().id)`. This ensures:
//   - Same RG → same names (idempotent deploys).
//   - Different RGs in the same subscription → different names (no
//     global-uniqueness collisions for Cosmos/Key Vault).
// The 13-char uniqueString hash leaves comfortable room under each
// resource type's name-length limit.

targetScope = 'resourceGroup'

// ============================================================================
// Parameters
// ============================================================================

@description('Azure region for everything EXCEPT Static Web Apps (which has its own location param because SWA Free is region-restricted). Defaults to the resource group location.')
param location string = resourceGroup().location

@description('Azure region for the Static Web App. SWA Free is restricted to five regions; centralindia is NOT one. Default eastasia is closest to India users.')
@allowed([
  'westus2'
  'centralus'
  'eastus2'
  'westeurope'
  'eastasia'
])
param staticWebAppLocation string = 'eastasia'

@description('Short prefix for resource names (3-10 lowercase chars). Combined with a per-RG hash for global uniqueness.')
@minLength(3)
@maxLength(10)
param resourcePrefix string = 'robberyrag'

@description('Environment tag (dev/staging/prod). Used in tags only; resources are NOT named differently per env. Deploy to a separate RG to isolate envs.')
@allowed([
  'dev'
  'staging'
  'prod'
])
param environment string = 'dev'

@description('Object ID of the principal running the deploy. Granted Key Vault Secrets Officer so initial secrets can be written. Run `az ad signed-in-user show --query id -o tsv` to get yours.')
param deployerPrincipalId string

@description('Type of deployerPrincipalId. User for interactive `az login`, ServicePrincipal for CI/CD.')
@allowed([
  'User'
  'ServicePrincipal'
  'Group'
])
param deployerPrincipalType string = 'User'

@description('Backend container image. Default is a public placeholder so first deploys succeed before CI has built the real image. The deploy script in 7.4 overrides this to ghcr.io/sarthakdixit/indian-robbery-rag:latest after the first CI build pushes.')
param backendImage string = 'mcr.microsoft.com/azuredocs/aci-helloworld'

@description('Email recipients for budget alerts (50/75/90/100% thresholds, see modules/budget-alerts.bicep). Pass as a Bicep array. Default is the project owner — override at deploy time for shared environments.')
param notificationEmails array = [
  'sarthak_dixit@outlook.com'
]

@description('Start date for the monthly budget (first day of a month, YYYY-MM-DD). Past dates within the current period are allowed; future dates limited to 3 months ahead. Update if deploying significantly after the file was written.')
param budgetStartDate string = '2026-06-01'

// ============================================================================
// Computed
// ============================================================================

// Deterministic suffix scoped to this RG. Stable across re-deploys.
var nameSuffix = uniqueString(resourceGroup().id)

// Per-resource names. Each must fit its type's length limit:
//   - Cosmos account:    3-44 chars
//   - Key Vault:         3-24 chars  ← tight; KV name omits prefix
//   - Log Analytics:     4-63 chars
//   - App Insights:      1-260 chars
//   - Managed Identity:  3-128 chars
//   - Managed Env:       2-260 chars (Container Apps env)
//   - Container App:     2-32 chars  ← tight; ca-robberyrag- (14) + suffix (13) = 27, just under
//   - Static Web App:    2-60 chars
var cosmosAccountName = toLower('${resourcePrefix}-cosmos-${nameSuffix}')
var keyVaultName = toLower('kv-${nameSuffix}')
var logAnalyticsWorkspaceName = toLower('${resourcePrefix}-law-${nameSuffix}')
var appInsightsName = toLower('${resourcePrefix}-appi-${nameSuffix}')
var managedIdentityName = toLower('${resourcePrefix}-backend-mi')
var managedEnvironmentName = toLower('${resourcePrefix}-cae-${nameSuffix}')
// Container App name: keep short to stay under 32-char limit.
// `ca-` (3) + suffix (13) = 16 chars; doesn't include prefix.
var containerAppName = toLower('ca-${nameSuffix}')
var staticWebAppName = toLower('${resourcePrefix}-swa-${nameSuffix}')

// Tags applied to every resource. Useful for cost-grouping in Azure
// Cost Management and for the budget alerts in 7.3.
var commonTags = {
  project: 'robbery-rag'
  environment: environment
  managedBy: 'bicep'
}

// ============================================================================
// Top-level resources (not in modules)
// ============================================================================

// User-assigned managed identity for the backend Container App.
// Declared HERE (not in container-apps module) so its principal ID is
// available for the Key Vault role assignment BEFORE the Container App
// itself deploys. Without this sequencing, the Container App's initial
// secret pull from Key Vault would fail with auth errors.
resource backendManagedIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: managedIdentityName
  location: location
  tags: commonTags
}

// ============================================================================
// Modules — order matches the implicit DAG
// ============================================================================

module cosmos 'modules/cosmos.bicep' = {
  name: 'cosmos-deployment'
  params: {
    location: location
    accountName: cosmosAccountName
    tags: commonTags
  }
}

module keyVault 'modules/key-vault.bicep' = {
  name: 'keyvault-deployment'
  params: {
    location: location
    vaultName: keyVaultName
    deployerPrincipalId: deployerPrincipalId
    deployerPrincipalType: deployerPrincipalType
    // The MI principal ID drives a conditional role assignment INSIDE
    // key-vault.bicep. Role assignments scoped to a vault must be
    // declared next to the vault resource (not via `existing` in main)
    // — see Bicep error BCP120. Passing the principal in here lets
    // key-vault.bicep create the role assignment with the vault as
    // a real resource scope.
    backendManagedIdentityPrincipalId: backendManagedIdentity.properties.principalId
    tags: commonTags
  }
}

module logAnalytics 'modules/log-analytics.bicep' = {
  name: 'loganalytics-deployment'
  params: {
    location: location
    workspaceName: logAnalyticsWorkspaceName
    appInsightsName: appInsightsName
    tags: commonTags
  }
}

module staticWebApp 'modules/static-web-app.bicep' = {
  name: 'swa-deployment'
  params: {
    location: staticWebAppLocation
    staticWebAppName: staticWebAppName
    tags: commonTags
  }
}

// ============================================================================
// Container Apps (depends on KV role assignment + log workspace key + SWA URL)
// ============================================================================
// The Container Apps module needs:
//   - The backend MI's resource ID (already in scope here)
//   - The Log Analytics workspace shared key — fetched from the module
//     output (not via `listKeys()` on an `existing` ref in main.bicep,
//     which fails with BCP307 because `existing` lookups happen at
//     deployment runtime, not at planning time when listKeys() is
//     evaluated)
//   - The Key Vault URI
//   - The Cosmos database + container names
//   - The SWA URL for CORS allowlist

module containerApps 'modules/container-apps.bicep' = {
  name: 'containerapps-deployment'
  params: {
    location: location
    resourcePrefix: resourcePrefix
    environmentName: managedEnvironmentName
    containerAppName: containerAppName
    backendImage: backendImage
    managedIdentityResourceId: backendManagedIdentity.id
    logAnalyticsWorkspaceCustomerId: logAnalytics.outputs.workspaceCustomerId
    logAnalyticsWorkspaceSharedKey: logAnalytics.outputs.workspaceSharedKey
    keyVaultUri: keyVault.outputs.vaultUri
    cosmosDatabaseName: cosmos.outputs.databaseName
    cosmosContainerName: cosmos.outputs.containerName
    // CORS: SWA URL + localhost ports for dev. The SWA URL is computed
    // via the staticWebApp module output (defaultUrl includes https://
    // prefix and no trailing slash, which is what FastAPI's
    // CORSMiddleware expects in allow_origins).
    corsAllowedOrigins: '${staticWebApp.outputs.defaultUrl},http://localhost:5173,http://localhost:4173'
    tags: commonTags
  }
}

// ============================================================================
// Budget alerts (no DAG dependencies — can deploy alongside everything)
// ============================================================================
// design.md AP-6: ₹500/month cap, 4-threshold email alerts. The auto-stop
// runbook (AP-7) was intentionally skipped — see infra/manual-kill-switch.md
// for the operator playbook that replaces it.

module budgetAlerts 'modules/budget-alerts.bicep' = {
  name: 'budget-deployment'
  params: {
    notificationEmails: notificationEmails
    startDate: budgetStartDate
  }
}

// ============================================================================
// Outputs
// ============================================================================
// These are consumed by:
//   1. The deploy script in 7.4 — `az deployment group create --query` reads
//      them to feed `az keyvault secret set` for runtime secrets, and to
//      override backendImage on subsequent deploys.
//   2. Operators — convenient to copy/paste into curl, az queries, etc.

// --- Cosmos ---
@description('Cosmos account name — input to subsequent az commands.')
output cosmosAccountName string = cosmos.outputs.accountName

@description('Cosmos endpoint URL (https://<account>.documents.azure.com:443).')
output cosmosEndpoint string = cosmos.outputs.endpoint

@description('Cosmos database name (matches Settings.cosmos_database_name).')
output cosmosDatabaseName string = cosmos.outputs.databaseName

@description('Cosmos container name (matches Settings.cosmos_container_name).')
output cosmosContainerName string = cosmos.outputs.containerName

@description('Cosmos resource ID — used for `az cosmosdb keys list` in the deploy script.')
output cosmosResourceId string = cosmos.outputs.accountResourceId

// --- Key Vault ---
@description('Key Vault name — used in `az keyvault secret set` and Container Apps `keyvaultref:` refs.')
output keyVaultName string = keyVault.outputs.vaultName

@description('Key Vault URI (https://<vault>.vault.azure.net/).')
output keyVaultUri string = keyVault.outputs.vaultUri

@description('Key Vault resource ID.')
output keyVaultResourceId string = keyVault.outputs.vaultResourceId

// --- Log Analytics + App Insights ---
@description('Log Analytics workspace name — for az monitor queries.')
output logAnalyticsWorkspaceName string = logAnalytics.outputs.workspaceName

@description('App Insights resource name.')
output appInsightsName string = logAnalytics.outputs.appInsightsName

// --- Backend Container App + MI ---
@description('Container App FQDN. The React frontend uses this as VITE_API_BASE_URL.')
output backendFqdn string = containerApps.outputs.containerAppFqdn

@description('Container App resource ID — for `az containerapp` operations including image updates.')
output backendResourceId string = containerApps.outputs.containerAppResourceId

@description('Backend MI principal ID — already granted Key Vault Secrets User in this deploy. Exposed for audit.')
output backendManagedIdentityPrincipalId string = backendManagedIdentity.properties.principalId

// --- Static Web App ---
@description('Static Web App default hostname (no scheme).')
output staticWebAppHostname string = staticWebApp.outputs.defaultHostname

@description('Full SWA URL. Open this in a browser after frontend deploy.')
output staticWebAppUrl string = staticWebApp.outputs.defaultUrl

@description('SWA name — used by `az staticwebapp secrets list` to fetch the deployment token for GitHub Actions.')
output staticWebAppName string = staticWebApp.outputs.staticWebAppName

// --- Budget ---
@description('Budget name — input to `az consumption budget show/delete`.')
output budgetName string = budgetAlerts.outputs.budgetName