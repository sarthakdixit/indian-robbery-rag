// Cosmos DB module — account, database, single type-discriminated container.
//
// Serverless capacity mode. Schema follows design.md §9: ONE container with
// partition key `/pk`, holding type-discriminated documents (rate_limit,
// query_log, cache_exact, cache_semantic, global_counter).
//
// Why serverless (not free tier):
//   The free tier is great when you can get it (1000 RU/s + 25 GB free
//   forever), but it's limited to ONE Cosmos account per subscription
//   and this subscription's free-tier slot is already used by another
//   project. Serverless was chosen as the next-best option because:
//
//   (a) Cost — at portfolio-demo scale (≤200 queries/day per design.md
//       FR-5 global cap), expected monthly RU consumption is ~300K RUs.
//       At $0.25/million RUs that's $0.08/month. Storage at ~100 MB
//       adds another $0.025/month. Total Cosmos cost: under ₹10/month,
//       comfortably inside the ₹500 budget.
//
//   (b) Idle behavior — serverless has zero idle cost, matching the
//       scale-to-zero Container Apps deployment. Provisioned 400 RU/s
//       (the minimum) would cost $24/month regardless of usage.
//
//   (c) Bursty traffic fit — Microsoft explicitly recommends serverless
//       for "intermittent and unpredictable traffic with long idle
//       times" (Cosmos serverless docs). That's exactly our profile.
//
// Constraints inherited from serverless mode (per Azure docs):
//   - Single region only. Adding more regions isn't supported.
//   - No throughput provisioning at database or container level —
//     `properties.options.throughput` must be omitted; setting it
//     returns an error.
//   - Free tier and serverless are mutually exclusive — the
//     `enableFreeTier` property must NOT be set.
//   - Per-container partition cap is 5000 RU/s. Hot partitions beyond
//     that throttle with HTTP 429. Not a concern at our scale.
//
// Naming: account names are 3-44 chars, all lowercase, globally unique.
// We default to `cosmos-<13-char-uniqueString>` (20 chars total) but
// allow the caller to override. The `uniqueString(resourceGroup().id)`
// pattern produces a deterministic suffix per resource group, so the
// same RG always yields the same name (good for idempotent deploys).

// ============================================================================
// Parameters
// ============================================================================

@description('Azure region for the Cosmos account. Defaults to the resource group location.')
param location string = resourceGroup().location

@description('Cosmos account name. Lowercase, 3-44 chars, globally unique. Defaults to a hashed name based on the resource group.')
@minLength(3)
@maxLength(44)
param accountName string = 'cosmos-${uniqueString(resourceGroup().id)}'

@description('Name of the Cosmos database holding all application documents.')
param databaseName string = 'robbery-rag'

@description('Name of the single shared container. Per design.md §9, we use one container for all document types.')
param containerName string = 'documents'

@description('Tags applied to every resource for cost-tracking and grouping.')
param tags object = {}

// ============================================================================
// Resources
// ============================================================================

// Cosmos DB account. `kind: 'GlobalDocumentDB'` is the SQL/NoSQL API
// which the backend's azure-cosmos SDK targets.
resource account 'Microsoft.DocumentDB/databaseAccounts@2024-05-15' = {
  name: toLower(accountName)
  location: location
  kind: 'GlobalDocumentDB'
  tags: tags
  properties: {
    databaseAccountOfferType: 'Standard'

    // Serverless capacity mode. Without this capability the account
    // defaults to provisioned throughput, which would charge ~$24/month
    // minimum even when idle. Account capacity mode is set at creation
    // and CANNOT be changed later — to switch modes you'd have to
    // delete and recreate the account.
    capabilities: [
      {
        name: 'EnableServerless'
      }
    ]

    // Session consistency is the sweet spot for our workload: stronger
    // than eventual (so a writer reads its own writes), weaker than
    // strong (so we don't pay multi-region replication latency). The
    // adapter's increment_counter relies on per-item atomicity, which
    // is honored regardless of the consistency level.
    consistencyPolicy: {
      defaultConsistencyLevel: 'Session'
    }

    // Single-region deployment. Serverless ONLY supports single region
    // (per Azure docs) — adding more regions on a serverless account
    // returns an error.
    locations: [
      {
        locationName: location
        failoverPriority: 0
        isZoneRedundant: false
      }
    ]

    // Security baseline:
    //   - publicNetworkAccess: 'Enabled' — Container Apps reaches Cosmos
    //     over the public endpoint. Tightening to private endpoints is
    //     a worthwhile follow-up but adds VNET complexity.
    //   - disableLocalAuth: false — we use connection-string auth from
    //     the backend. Switching to managed-identity auth would set this
    //     to true. Documented as a follow-up in design.md tech debt.
    //   - minimalTlsVersion: 'Tls12' — TLS 1.0/1.1 disabled.
    publicNetworkAccess: 'Enabled'
    disableLocalAuth: false
    minimalTlsVersion: 'Tls12'

    // Defaults that we want to be explicit about:
    enableAnalyticalStorage: false      // we don't query via Synapse
    enableAutomaticFailover: false      // single region, no failover
    enableMultipleWriteLocations: false // single region writes only
  }
}

// SQL database. design.md §9 + the adapter's schema use a single
// database holding one container. In serverless mode, throughput
// CANNOT be provisioned at the database or container level — Azure
// rejects `properties.options.throughput` outright. Billing happens
// per-request at $0.25/million RUs.
resource database 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases@2024-05-15' = {
  parent: account
  name: databaseName
  properties: {
    resource: {
      id: databaseName
    }
  }
}

// The single shared container. Partition key `/pk` matches the
// CosmosDocumentStore adapter, which writes every item with a `pk`
// field. TTL=-1 enables per-document TTL (each item sets its own
// `ttl` field) without applying a blanket TTL to undocumented items.
//
// Indexing policy: explicitly include the fields we query on (`pk`,
// `id`) and exclude the heavy `body` subtree to save RU/s on writes.
// We never query inside `body`; the read path is always point-lookup
// by (pk, id) or `SELECT * FROM c WHERE c.pk = @pk` (list_by_partition).
resource container 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-05-15' = {
  parent: database
  name: containerName
  properties: {
    resource: {
      id: containerName
      partitionKey: {
        paths: ['/pk']
        kind: 'Hash'
      }
      defaultTtl: -1
      indexingPolicy: {
        indexingMode: 'consistent'
        automatic: true
        // Index everything by default, then exclude what we know we
        // never query into. The opposite pattern (include-only) would
        // require explicitly listing every queryable path — fragile,
        // and explicit `/id/?` is rejected by Cosmos because `id` is a
        // system property auto-indexed at all times. `pk` is the
        // partition key and is also auto-indexed under the include-all
        // strategy.
        includedPaths: [
          {
            path: '/*'
          }
        ]
        excludedPaths: [
          // /body/* contains arbitrary user data (query text,
          // embeddings, citation lists). Excluding it saves write
          // RU/s while keeping reads (which fetch the whole doc)
          // unchanged.
          {
            path: '/body/*'
          }
          // _etag is a Cosmos system field — we never query on it
          // and excluding it is a documented best practice.
          {
            path: '/_etag/?'
          }
        ]
      }
    }
  }
}

// ============================================================================
// Outputs
// ============================================================================
// Names + endpoints are read by main.bicep and downstream modules (e.g.,
// Container Apps env vars). We deliberately do NOT output the connection
// string here — that goes via Key Vault to avoid leaking it into the
// Azure deployment history.

@description('The Cosmos account name (input into other modules + the deploy script).')
output accountName string = account.name

@description('Cosmos account endpoint URL.')
output endpoint string = account.properties.documentEndpoint

@description('Database name (matches Settings.cosmos_database_name in the backend).')
output databaseName string = database.name

@description('Container name (matches Settings.cosmos_container_name in the backend).')
output containerName string = container.name

@description('Resource ID — useful for role assignments downstream.')
output accountResourceId string = account.id