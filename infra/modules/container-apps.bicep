// Container Apps module — managed environment + Container App.
//
// TWO RESOURCES, IN ORDER:
//
//   1. Microsoft.App/managedEnvironments — the shared compute layer.
//      Ships container logs to the Log Analytics workspace from
//      log-analytics.bicep via the workspace customer ID + shared key
//      (the caller is responsible for fetching the shared key via
//      listKeys() and passing it in; we don't compute it here because
//      the workspace lives in a different module).
//
//   2. Microsoft.App/containerApps — the actual backend, attached to a
//      user-assigned MI (created in main.bicep), with ingress on 8000,
//      scale-to-zero, env vars, and Key Vault secret refs.
//
// THE MANAGED IDENTITY itself is NOT created here — it's a top-level
// resource in main.bicep. We accept its resource ID as a parameter.
// Reason: the documented chicken-and-egg with Container Apps + Key
// Vault secret refs requires the MI to have Key Vault access BEFORE
// the Container App provisions, but a system-assigned MI doesn't have
// a principal ID until after the Container App is created. Main.bicep
// creates the user-assigned MI first, grants it Key Vault Secrets
// User role on the vault, THEN deploys this module — by which time
// the secret-pull path is already authorized.
//
// THE ROLE ASSIGNMENT granting the MI Key Vault Secrets User on the
// vault is also in main.bicep, where both the MI and vault are visible.
//
// IMAGE STRATEGY:
//
// At first deploy, no image exists in ghcr.io yet (CI hasn't built
// one). We default `backendImage` to a tiny public placeholder
// (`mcr.microsoft.com/azuredocs/aci-helloworld`) so Bicep can succeed.
// The deploy script in 7.4 will pass `backendImage=ghcr.io/...:latest`
// after CI builds the real image. Re-running `az deployment group
// create` without passing backendImage would revert to the placeholder
// — so 7.4's deploy script always sets it.
//
// ALL SECRETS are pulled at runtime via Key Vault references; nothing
// sensitive lives in this Bicep template or in deployment history.

// ============================================================================
// Parameters
// ============================================================================

@description('Azure region for the managed environment, MI, and Container App.')
param location string = resourceGroup().location

@description('Resource name prefix used to derive names for the managed environment and Container App.')
param resourcePrefix string

@description('Managed environment name.')
param environmentName string = '${resourcePrefix}-cae'

@description('Container App name.')
param containerAppName string = '${resourcePrefix}-backend'

@description('Resource ID of the user-assigned managed identity to attach to the Container App. The MI must already exist AND have the Key Vault Secrets User role on the vault before this module deploys; otherwise the initial secret pull at app startup fails with "Unable to get value using Managed identity ... for secret". main.bicep handles both prerequisites.')
param managedIdentityResourceId string

@description('Backend container image. Default is a public placeholder so first deploys succeed before CI has built the real image. The deploy script in 7.4 overrides this to ghcr.io/sarthakdixit/indian-robbery-rag:latest after CI builds.')
param backendImage string = 'mcr.microsoft.com/azuredocs/aci-helloworld'

@description('Log Analytics workspace customer ID (a GUID). From log-analytics.bicep output.')
param logAnalyticsWorkspaceCustomerId string

@description('Log Analytics workspace primary shared key. Must be fetched via listKeys() in main.bicep; we accept it as a secure param so it never lands in deployment history.')
@secure()
param logAnalyticsWorkspaceSharedKey string

@description('Key Vault URI from key-vault.bicep output. Format: https://<name>.vault.azure.net/ (trailing slash required).')
param keyVaultUri string

@description('Comma-separated list of allowed CORS origins. The backend uses exact-match (FastAPI allow_origins) — wildcards like "*.azurestaticapps.net" do NOT work. main.bicep passes the exact SWA defaultHostname URL after the SWA is created. Default here is localhost-only so the module works standalone if needed.')
param corsAllowedOrigins string = 'http://localhost:5173,http://localhost:4173'

@description('Cosmos database name. Matches the Settings.cosmos_database_name in the backend; must match the Bicep output from cosmos.bicep.')
param cosmosDatabaseName string = 'robbery-rag'

@description('Cosmos container name. Matches the Settings.cosmos_container_name in the backend; must match the Bicep output from cosmos.bicep.')
param cosmosContainerName string = 'documents'

@description('CPU allocation in vCPU. 0.5 is sufficient for our FastAPI + embedded ChromaDB workload and stays in the Consumption free-grant range.')
param containerCpu string = '0.5'

@description('Memory allocation. Must be paired with CPU per Container Apps allowed combinations; "1.0Gi" pairs with "0.5" CPU.')
param containerMemory string = '1.0Gi'

@description('Tags applied to all three resources.')
param tags object = {}

// ============================================================================
// Resources
// ============================================================================

// 1. Managed environment. Logs route to the Log Analytics workspace.
resource environment 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: environmentName
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalyticsWorkspaceCustomerId
        sharedKey: logAnalyticsWorkspaceSharedKey
      }
    }
    // Workload profiles intentionally NOT set — that defaults the
    // environment to the Consumption-only plan, which is the cheaper
    // option with true scale-to-zero. Workload profiles add fixed cost.
    zoneRedundant: false
  }
}

// 2. The Container App itself. References:
//      - environment.id (created first in this module)
//      - managedIdentityResourceId (param; main.bicep created the MI
//        and granted it Key Vault access BEFORE this module deploys)
//
// Key Vault secret references use the user-assigned identity (the
// identity field on each secret takes the MI's resource ID).
resource containerApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: containerAppName
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${managedIdentityResourceId}': {}
    }
  }
  properties: {
    managedEnvironmentId: environment.id
    configuration: {
      activeRevisionsMode: 'Single'

      // External ingress on 8000 (the port the backend listens on per
      // backend/Dockerfile + entrypoint.sh). Container Apps fronts this
      // with managed HTTPS automatically.
      ingress: {
        external: true
        targetPort: 8000
        transport: 'http'
        allowInsecure: false
        traffic: [
          {
            weight: 100
            latestRevision: true
          }
        ]
      }

      // Secrets pulled at startup from Key Vault. Each entry maps a
      // local secret name (used by the env var refs below) to a Key
      // Vault secret URL. Identity = the user-assigned MI's resource
      // ID, which must have Key Vault Secrets User role on the vault
      // (granted by main.bicep). If the role assignment is missing,
      // Container App provisioning fails with
      //   "Unable to get value using Managed identity ... for secret".
      secrets: [
        {
          name: 'gemini-api-key'
          keyVaultUrl: '${keyVaultUri}secrets/gemini-api-key'
          identity: managedIdentityResourceId
        }
        {
          name: 'cosmos-connection-string'
          keyVaultUrl: '${keyVaultUri}secrets/cosmos-connection-string'
          identity: managedIdentityResourceId
        }
        {
          name: 'ip-hash-salt'
          keyVaultUrl: '${keyVaultUri}secrets/ip-hash-salt'
          identity: managedIdentityResourceId
        }
        {
          name: 'admin-password'
          keyVaultUrl: '${keyVaultUri}secrets/admin-password'
          identity: managedIdentityResourceId
        }
        {
          name: 'turnstile-secret-key'
          keyVaultUrl: '${keyVaultUri}secrets/turnstile-secret-key'
          identity: managedIdentityResourceId
        }
        {
          name: 'appinsights-connection-string'
          keyVaultUrl: '${keyVaultUri}secrets/appinsights-connection-string'
          identity: managedIdentityResourceId
        }
      ]
    }

    template: {
      containers: [
        {
          name: 'backend'
          image: backendImage
          resources: {
            cpu: json(containerCpu)
            memory: containerMemory
          }
          env: [
            // Non-sensitive config — plain values.
            {
              name: 'ENVIRONMENT'
              value: 'cloud'
            }
            {
              name: 'COSMOS_DATABASE_NAME'
              value: cosmosDatabaseName
            }
            {
              name: 'COSMOS_CONTAINER_NAME'
              value: cosmosContainerName
            }
            {
              name: 'CORS_ALLOWED_ORIGINS'
              value: corsAllowedOrigins
            }
            // Sensitive config — pulled from Key Vault via secret refs.
            {
              name: 'GEMINI_API_KEY'
              secretRef: 'gemini-api-key'
            }
            {
              name: 'COSMOS_CONNECTION_STRING'
              secretRef: 'cosmos-connection-string'
            }
            {
              name: 'IP_HASH_SALT'
              secretRef: 'ip-hash-salt'
            }
            {
              name: 'ADMIN_PASSWORD'
              secretRef: 'admin-password'
            }
            {
              name: 'TURNSTILE_SECRET_KEY'
              secretRef: 'turnstile-secret-key'
            }
            {
              name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
              secretRef: 'appinsights-connection-string'
            }
          ]
        }
      ]
      scale: {
        minReplicas: 0
        maxReplicas: 1
        rules: [
          {
            name: 'http-scale'
            http: {
              metadata: {
                concurrentRequests: '50'
              }
            }
          }
        ]
      }
    }
  }
}

// ============================================================================
// Outputs
// ============================================================================

@description('Container App FQDN — used by the React frontend as VITE_API_BASE_URL.')
output containerAppFqdn string = containerApp.properties.configuration.ingress.fqdn

@description('Container App resource ID.')
output containerAppResourceId string = containerApp.id

@description('Managed environment resource ID — useful for downstream resources or SWA linked-backend (if upgraded to Standard).')
output managedEnvironmentResourceId string = environment.id