// Key Vault module — stores backend secrets that the Container Apps
// runtime reads via `keyvaultref:` secret references.
//
// Secrets stored here (populated by the deploy script in 7.4, NOT here):
//   - gemini-api-key         — Gemini generation + embeddings API key
//   - cosmos-connection-string — written from cosmos.bicep output
//   - ip-hash-salt           — salt for SHA-256(IP) in request logs
//   - admin-password         — gates /api/admin/* endpoints
//   - turnstile-secret-key   — Cloudflare Turnstile server-side key
//   - appinsights-connection-string — App Insights ingestion endpoint
//
// We deliberately don't create the secrets in Bicep. Two reasons:
//   1. Secrets in Bicep parameters end up in deployment history (the
//      Azure portal stores it). The deploy script uses `az keyvault
//      secret set` after the vault exists, which doesn't leak.
//   2. Re-deployments would overwrite secrets that were rotated
//      manually post-deploy. Imperative writes via the script let the
//      operator decide.
//
// RBAC authorization mode (enableRbacAuthorization: true) is the modern
// pattern. The legacy "access policy" model is on the way out. RBAC
// grants are made in 7.2 once Container Apps managed identity exists.

// ============================================================================
// Parameters
// ============================================================================

@description('Azure region for the Key Vault. Should match the rest of the deploy.')
param location string = resourceGroup().location

@description('Key Vault name. Must be globally unique, 3-24 chars, alphanumeric with hyphens.')
@minLength(3)
@maxLength(24)
param vaultName string = 'kv-${uniqueString(resourceGroup().id)}'

@description('Object ID (NOT app ID) of the principal running the deploy. Granted Secrets Officer so the deploy script can write initial secret values. Pass via `az ad signed-in-user show --query id` or a GitHub-Actions service principal.')
param deployerPrincipalId string

@description('Type of principal in deployerPrincipalId. Use "User" for interactive `az login` deploys, "ServicePrincipal" for CI/CD identities.')
@allowed([
  'User'
  'ServicePrincipal'
  'Group'
])
param deployerPrincipalType string = 'User'

@description('Principal ID of the backend Container App managed identity. Granted Key Vault Secrets User role so the Container App can resolve keyvaultref: secret references at runtime. Pass empty string ("") to skip — useful for chunk 7.1 standalone deploy before the MI exists. Always populated by main.bicep at chunk 7.2 onward.')
param backendManagedIdentityPrincipalId string = ''

@description('Tenant ID of the subscription. Defaults to the current tenant.')
param tenantId string = subscription().tenantId

@description('Tags applied to every resource for cost-tracking and grouping.')
param tags object = {}

// ============================================================================
// Resources
// ============================================================================

// Built-in role definition IDs.
// `Key Vault Secrets Officer` — read/write/delete secrets. Granted to
// the deploy principal so the post-create script can `az keyvault
// secret set` the runtime values.
// `Key Vault Secrets User` — read secret VALUES only. Granted to the
// backend Container App's managed identity so it can resolve
// keyvaultref: secret references at startup.
// Source: https://learn.microsoft.com/azure/role-based-access-control/built-in-roles
var keyVaultSecretsOfficerRoleId = 'b86a8fe4-44ce-4948-aee5-eccb2c155cd7'
var keyVaultSecretsUserRoleId = '4633458b-17de-408a-b874-0445c86b69e6'

resource vault 'Microsoft.KeyVault/vaults@2024-04-01-preview' = {
  name: vaultName
  location: location
  tags: tags
  properties: {
    tenantId: tenantId

    // Standard SKU is fine for our scale. Premium adds HSM-backed keys
    // which we don't need (we only store secrets, not keys).
    sku: {
      family: 'A'
      name: 'standard'
    }

    // Modern auth. Granting access happens via role assignments below
    // and in 7.2 (where Container Apps' managed identity is created).
    enableRbacAuthorization: true

    // Soft delete is required by Azure (cannot be disabled). 7-day
    // retention is the minimum — sufficient for our recovery window.
    // Default would be 90; shorter retention means the teardown script
    // can recreate the vault sooner if needed.
    enableSoftDelete: true
    softDeleteRetentionInDays: 7

    // enablePurgeProtection must be `null` (not `false`). Azure's ARM
    // API rejects `false` outright with "Enabling the purge protection
    // for a vault is an irreversible action." Bicep's `null` keyword
    // tells the deployment engine to skip the property entirely — ARM
    // then applies its default (off). Confirmed via Azure/bicep
    // discussion #1729: "setting the value to null... is handled by
    // the resource as if the property was not declared."
    //
    // Omitting the line entirely doesn't work in Bicep: Bicep
    // serializes omitted booleans as `false` in the ARM JSON body,
    // which ARM then rejects. `null` is the only way to suppress.
    //
    // If you DO want purge protection (one-way! you cannot disable
    // without waiting out the retention period AND the tenant-level
    // 90-day cooldown), replace this with: enablePurgeProtection: true
    enablePurgeProtection: null

    // Public access — Container Apps reaches Key Vault over the public
    // endpoint. Tightening via private endpoints requires VNET, which
    // we skip for cost (free-tier Container Apps environment doesn't
    // support VNET integration without uplift).
    publicNetworkAccess: 'Enabled'
    networkAcls: {
      defaultAction: 'Allow'
      bypass: 'AzureServices'
    }

    // Don't allow VM/ARM deployments to access secrets. We never need
    // this and it tightens the blast radius.
    enabledForDeployment: false
    enabledForDiskEncryption: false
    enabledForTemplateDeployment: false
  }
}

// Grant the deployer Secrets Officer so they can write initial secrets
// via `az keyvault secret set`. Without this, the post-deploy script
// gets a 403. The role assignment is scoped to THIS vault, not the
// subscription, so it's the minimum privilege.
resource deployerRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  // Role assignment name must be a GUID. We derive a deterministic one
  // from (vault, principal, role) so re-deploys don't create duplicates.
  name: guid(vault.id, deployerPrincipalId, keyVaultSecretsOfficerRoleId)
  scope: vault
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      keyVaultSecretsOfficerRoleId
    )
    principalId: deployerPrincipalId
    // Explicit principalType avoids a race where the principal hasn't
    // propagated yet. User for interactive `az login`, ServicePrincipal
    // for CI/CD identities (e.g., GitHub OIDC).
    principalType: deployerPrincipalType
  }
}

// Conditional role assignment for the backend Container App's MI.
// Created only when the principal ID is provided (i.e., from chunk 7.2's
// main.bicep). Standalone 7.1 deploys pass "" and skip this.
//
// This MUST be in this module (not main.bicep) because role assignments
// scoped to a resource require the scope target to be a "real" Bicep
// resource — not an `existing` reference — so the resource ID is
// available at deployment planning time. See Bicep error BCP120.
resource backendRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(backendManagedIdentityPrincipalId)) {
  name: guid(vault.id, backendManagedIdentityPrincipalId, keyVaultSecretsUserRoleId)
  scope: vault
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      keyVaultSecretsUserRoleId
    )
    principalId: backendManagedIdentityPrincipalId
    principalType: 'ServicePrincipal'
  }
}

// ============================================================================
// Outputs
// ============================================================================

@description('Key Vault name — referenced by Container Apps secret refs (`keyvaultref:<name>,<secret>`).')
output vaultName string = vault.name

@description('Key Vault URI — used by SDK clients that connect directly (e.g., if we later switch to managed-identity for Cosmos).')
output vaultUri string = vault.properties.vaultUri

@description('Resource ID — useful for downstream role assignments (Container Apps managed identity gets Secrets User).')
output vaultResourceId string = vault.id