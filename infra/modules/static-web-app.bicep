// Static Web App module — Free tier, hosts the React frontend.
//
// SCOPE: just provisions the SWA resource. Deploy of the actual built
// React bundle happens via the existing GitHub Actions workflow
// (.github/workflows/frontend-deploy.yml from Batch 0.4), which uses
// the deployment token output by this resource.
//
// PROVIDER: 'Custom' (bring-your-own workflow), NOT 'GitHub'. We chose
// this because:
//   1. The 'GitHub' provider would have Bicep create the deploy
//      workflow file in the repo on first deploy, which requires
//      passing a GitHub PAT through Bicep. That PAT would land in
//      deployment history.
//   2. The Batch 0.4 workflow already exists and works. Re-using it
//      avoids drift between what Bicep generates and what we hand-
//      authored.
//
// LOCATION QUIRK: SWA Free is only available in five regions:
// westus2, centralus, eastus2, westeurope, eastasia. centralindia
// (where the rest of our stack lives) is NOT on that list. So this
// module takes its own location parameter, defaulting to eastasia
// (the geographically closest supported region for India users).
// The SWA edge CDN serves traffic globally regardless of the chosen
// resource region.
//
// NO LINKED BACKEND. design.md FR-1 + 7.2 decision: SWA Free, React
// talks directly to the Container App via its public FQDN. The
// linked-backend feature requires SWA Standard ($9/month) and isn't
// worth that cost for a portfolio demo.

// ============================================================================
// Parameters
// ============================================================================

@description('Static Web App name. Must be unique within the resource group.')
param staticWebAppName string

@description('Azure region. SWA Free is restricted to five regions; centralindia is NOT supported. Default eastasia is closest to India.')
@allowed([
  'westus2'
  'centralus'
  'eastus2'
  'westeurope'
  'eastasia'
])
param location string = 'eastasia'

@description('Tags applied to the resource.')
param tags object = {}

// ============================================================================
// Resources
// ============================================================================

resource staticWebApp 'Microsoft.Web/staticSites@2024-04-01' = {
  name: staticWebAppName
  location: location
  tags: tags
  sku: {
    name: 'Free'
    tier: 'Free'
  }
  properties: {
    // 'Custom' = bring-your-own workflow. The existing
    // .github/workflows/frontend-deploy.yml uses
    // azure/static-web-apps-deploy@v1 with the deployment token to
    // push the built React bundle.
    provider: 'Custom'

    // allowConfigFileUpdates: true lets staticwebapp.config.json in
    // the deployed bundle override SWA settings. We rely on this for
    // routing (SPA fallback, redirects, response headers).
    allowConfigFileUpdates: true

    // stagingEnvironmentPolicy: 'Disabled' on Free since preview
    // environments are a Standard-tier feature anyway. Setting it
    // explicit so behavior doesn't drift if Azure ever flips defaults.
    stagingEnvironmentPolicy: 'Disabled'

    // enterpriseGradeCdnStatus: 'Disabled' — this is the toggle for
    // Front Door integration. Free tier doesn't support it; explicit
    // for clarity.
    enterpriseGradeCdnStatus: 'Disabled'
  }
}

// ============================================================================
// Outputs
// ============================================================================

@description('Default hostname (without scheme), e.g. "abc-1234.eastasia.5.azurestaticapps.net".')
output defaultHostname string = staticWebApp.properties.defaultHostname

@description('Full HTTPS URL of the SWA, used in CORS_ALLOWED_ORIGINS on the Container App.')
output defaultUrl string = 'https://${staticWebApp.properties.defaultHostname}'

@description('Resource ID — for downstream references (custom domains, linked backends if upgraded to Standard).')
output staticWebAppResourceId string = staticWebApp.id

@description('Static Web App resource name — for downstream az commands like deployment token retrieval.')
output staticWebAppName string = staticWebApp.name