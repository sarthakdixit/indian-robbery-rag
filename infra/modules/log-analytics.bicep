// Log Analytics + Application Insights module.
//
// Creates two resources:
//   1. Microsoft.OperationalInsights/workspaces — the Log Analytics
//      workspace. Both Container Apps (logs) and App Insights (telemetry)
//      ingest into this single workspace, which keeps querying simple
//      and stays within the free-tier 5 GB/month ingestion allowance.
//
//   2. Microsoft.Insights/components — the App Insights component, in
//      workspace-based mode (the only supported mode since classic App
//      Insights was retired in Feb 2024). Configured to write all
//      telemetry into the workspace from step 1.
//
// The Container App in container-apps.bicep references the workspace's
// customerId + sharedKey for its log destination, and reads the App
// Insights connection string from Key Vault (set by the deploy script).
//
// Pricing posture: PerGB2018 SKU + 30-day retention is the cheapest
// available config. Free-tier allowance is 5 GB ingestion/month. At our
// scale we ingest <100 MB/month, comfortably free. The `dailyQuotaGb`
// guardrail caps ingestion at 1 GB/day; if a runaway log loop blasts
// that ceiling, ingestion stops for the rest of the day rather than
// silently piling up charges. Cosmetic at our scale but defensive.

// ============================================================================
// Parameters
// ============================================================================

@description('Azure region for both the workspace and App Insights component.')
param location string = resourceGroup().location

@description('Log Analytics workspace name. Globally unique within the subscription; the per-RG hash suffix in main.bicep ensures this.')
@minLength(4)
@maxLength(63)
param workspaceName string

@description('Application Insights component name.')
@minLength(1)
@maxLength(260)
param appInsightsName string

@description('Daily ingestion cap in GB for the workspace. Stops ingestion when exceeded — prevents runaway log loops from blowing past the free tier. -1 means no cap.')
@minValue(-1)
param dailyQuotaGb int = 1

@description('Tags applied to both resources.')
param tags object = {}

// ============================================================================
// Resources
// ============================================================================

// Log Analytics workspace. PerGB2018 is the only SKU available for new
// workspaces; legacy SKUs (Standard, Premium) are no longer accepted.
resource workspace 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: workspaceName
  location: location
  tags: tags
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    // 30 days is the maximum retention included in PerGB2018 at no
    // extra cost. Longer retention is billable; we don't need it.
    retentionInDays: 30
    workspaceCapping: {
      dailyQuotaGb: dailyQuotaGb
    }
    features: {
      // Required when this workspace is later referenced by other
      // resources (App Insights, Container Apps env). The default
      // is true on new workspaces; setting explicitly for clarity.
      enableLogAccessUsingOnlyResourcePermissions: true
    }
    publicNetworkAccessForIngestion: 'Enabled'
    publicNetworkAccessForQuery: 'Enabled'
  }
}

// Workspace-based App Insights component. The legacy "classic" mode
// (no WorkspaceResourceId) was retired in Feb 2024 — all new components
// MUST be workspace-based.
//
// `kind: 'web'` is the right value for HTTP/REST APIs like our FastAPI
// backend; it controls which telemetry tables are emphasized in the
// portal. Use 'other' for non-web workloads.
//
// `Flow_Type: 'Bluefield'` indicates the component was created via
// ARM/Bicep (not the portal's "create new" flow), and tells Azure not
// to provision a brand-new workspace for us — we're bringing our own.
resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: appInsightsName
  location: location
  kind: 'web'
  tags: tags
  properties: {
    Application_Type: 'web'
    Flow_Type: 'Bluefield'
    Request_Source: 'rest'
    WorkspaceResourceId: workspace.id
    IngestionMode: 'LogAnalytics'
    publicNetworkAccessForIngestion: 'Enabled'
    publicNetworkAccessForQuery: 'Enabled'
    // Sampling at 100% — we have very low traffic, so dropping
    // telemetry to save money is unnecessary. Lower if traffic ever
    // climbs to thousands of req/min.
    SamplingPercentage: 100
  }
}

// ============================================================================
// Outputs
// ============================================================================

@description('Workspace resource ID — Container Apps managed environment references this for log routing.')
output workspaceResourceId string = workspace.id

@description('Workspace customer ID (a GUID, also called "workspaceId" in some APIs). Used by the Container Apps env to authenticate log ingestion.')
output workspaceCustomerId string = workspace.properties.customerId

@description('Workspace name — for downstream az queries.')
output workspaceName string = workspace.name

@description('App Insights resource ID — useful for tagging downstream resources.')
output appInsightsResourceId string = appInsights.id

@description('App Insights name — for downstream az queries.')
output appInsightsName string = appInsights.name

@description('App Insights connection string. Will be stored in Key Vault by the deploy script (NOT exposed via deployment outputs in main.bicep) so the value doesnt land in deployment history.')
output appInsightsConnectionString string = appInsights.properties.ConnectionString

@description('Workspace primary shared key. Needed by the Container Apps managed environment for log ingestion. @secure() redacts the value from the deployment history view. Bicep computes listKeys() at deployment time, so it can only be done here (in the module that owns the workspace as a real resource); referencing the workspace via `existing` in main.bicep and calling listKeys() there fails with BCP307.')
@secure()
output workspaceSharedKey string = workspace.listKeys().primarySharedKey