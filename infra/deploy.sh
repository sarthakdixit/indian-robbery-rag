#!/usr/bin/env bash
# deploy.sh — Azure infrastructure deployment for indian-robbery-rag
#
# USAGE:
#   ./deploy.sh init        # First-time deploy: seed placeholders + Bicep
#   ./deploy.sh secrets     # Populate real Key Vault secret values
#   ./deploy.sh image TAG   # Update Container App to a new image tag
#   ./deploy.sh all         # init + secrets + restart Container App
#   ./deploy.sh status      # Print current deployment endpoints/state
#   ./deploy.sh help        # This help text
#
# PREREQUISITES:
#   - az CLI logged in (`az login`) to the right subscription
#   - `az bicep` available (auto-installed by Azure CLI on first use)
#   - Environment variables for `secrets` subcommand:
#       GEMINI_API_KEY            (from https://aistudio.google.com/apikey)
#       ADMIN_PASSWORD            (set this yourself; 16+ random chars)
#       TURNSTILE_SECRET_KEY      (from Cloudflare Turnstile dashboard)
#   - Network: outbound HTTPS to *.azure.com, *.microsoftonline.com
#
# IDEMPOTENCY: Every subcommand can be run repeatedly. Secrets that
# already hold non-placeholder values are NOT overwritten (so the IP
# hash salt stays stable across re-deploys — critical because rate-limit
# entries hash IPs with this salt).
#
# WHAT INIT DOES (in order):
#   1. Verify prerequisites
#   2. Compute the deployer principal ID
#   3. Ensure the resource group exists
#   4. (After Bicep deploys the vault) seed placeholder secrets so the
#      Container App's keyVaultUrl secret refs validate at create time
#      — Azure refuses to create a Container App if any referenced
#      secret doesn't exist, even with `placeholder-will-be-replaced`
#      as the value. See infra/post-deploy-checklist.md
#   5. Run the Bicep deployment
#   6. Print endpoint URLs
#
# WHAT SECRETS DOES:
#   1. Read user-provided values from env vars
#   2. Generate a stable IP hash salt if one doesn't exist already
#   3. Fetch cosmos-connection-string from `az cosmosdb keys list`
#   4. Fetch appinsights-connection-string from `az monitor app-insights ...`
#   5. Upsert all 6 secrets to Key Vault
#   6. Restart the Container App so the new values are picked up
#
# WHAT IMAGE DOES:
#   1. Validate the tag exists in GHCR (best-effort — public registry)
#   2. Call `az containerapp update --image` which creates a new revision

set -euo pipefail

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
# These match the Bicep parameters and computed names in infra/main.bicep.
# Update both files in sync if any of these change.
readonly RG="${RG:-rg-robberyrag-dev}"
readonly LOCATION="${LOCATION:-centralindia}"
readonly RESOURCE_PREFIX="robberyrag"
readonly BICEP_FILE="infra/main.bicep"
readonly PARAMS_FILE="infra/parameters.json"

# The six secrets that MUST exist in Key Vault before the Container App
# can provision its secret refs. Order doesn't matter; names must match
# what container-apps.bicep references.
readonly SECRET_NAMES=(
    gemini-api-key
    cosmos-connection-string
    ip-hash-salt
    admin-password
    turnstile-secret-key
    appinsights-connection-string
)

# Placeholder value used during init. Long-enough string that won't
# accidentally resemble a real credential. The `secrets` subcommand
# detects this string to decide whether to overwrite.
readonly PLACEHOLDER_VALUE="placeholder-will-be-replaced-by-deploy-script"

# ---------------------------------------------------------------------------
# Pretty-printing helpers (kept minimal — no external deps)
# ---------------------------------------------------------------------------
log()    { printf '\033[1;34m[deploy]\033[0m %s\n' "$*" >&2; }
warn()   { printf '\033[1;33m[deploy]\033[0m %s\n' "$*" >&2; }
err()    { printf '\033[1;31m[deploy]\033[0m %s\n' "$*" >&2; }
ok()     { printf '\033[1;32m[deploy]\033[0m %s\n' "$*" >&2; }
heading() {
    printf '\n\033[1;36m========================================\033[0m\n' >&2
    printf '\033[1;36m  %s\033[0m\n' "$*" >&2
    printf '\033[1;36m========================================\033[0m\n\n' >&2
}

# ---------------------------------------------------------------------------
# Subcommand: help
# ---------------------------------------------------------------------------
cmd_help() {
    head -45 "$0" | grep -E '^#( |$)' | sed 's/^# \{0,1\}//'
    exit 0
}

# ---------------------------------------------------------------------------
# Prerequisite checks
# ---------------------------------------------------------------------------
check_prereqs() {
    log "Verifying prerequisites..."

    command -v az >/dev/null 2>&1 || {
        err "az CLI not found. Install from https://aka.ms/azcli"
        exit 1
    }

    az account show >/dev/null 2>&1 || {
        err "az not logged in. Run: az login"
        exit 1
    }

    [[ -f "$BICEP_FILE" ]] || {
        err "Bicep file not found at $BICEP_FILE. Run from repo root."
        exit 1
    }

    [[ -f "$PARAMS_FILE" ]] || {
        err "Parameters file not found at $PARAMS_FILE. Run from repo root."
        exit 1
    }

    # Configure az to never prompt for extension installation.
    # Some `az` commands (notably `az monitor app-insights component show`)
    # belong to extensions that aren't auto-installed. In an interactive
    # terminal, az shows a prompt — but inside command substitution like
    # $(...) the prompt's stdin is the script's, and stdout is captured,
    # so the user never SEES the prompt and the script appears hung. This
    # config tells az to install extensions automatically without asking.
    # `--only-show-errors` suppresses the "config set" confirmation lines.
    az config set extension.use_dynamic_install=yes_without_prompt --only-show-errors >/dev/null 2>&1 || true
    az config set extension.dynamic_install_allow_preview=false    --only-show-errors >/dev/null 2>&1 || true

    ok "Prerequisites OK."
}

# ---------------------------------------------------------------------------
# Look up Key Vault name from a deployed RG (or compute it from prefix
# if not yet deployed).
#
# The vault name is `kv-${uniqueString(rg-id)}` per the Bicep, which we
# can't compute locally without re-implementing ARM's uniqueString. So
# we read it back from the last deployment's outputs after init.
# ---------------------------------------------------------------------------
get_vault_name() {
    # Try the last TOP-LEVEL deployment's outputs first. Module
    # deployments (e.g., 'keyvault-deployment') don't expose a
    # 'keyVaultName' output at the top-level shape we want; only the
    # main.bicep deployment does. Filter accordingly.
    local vault_name
    vault_name=$(az deployment group list \
        --resource-group "$RG" \
        --query "sort_by([?starts_with(name, 'deploy-') && properties.provisioningState=='Succeeded'], &properties.timestamp) | reverse(@)[0].properties.outputs.keyVaultName.value" \
        -o tsv 2>/dev/null || echo "")

    if [[ -z "$vault_name" || "$vault_name" == "null" ]]; then
        # Fall back to listing vaults in the RG (single-vault assumption)
        vault_name=$(az keyvault list \
            --resource-group "$RG" \
            --query "[0].name" \
            -o tsv 2>/dev/null || echo "")
    fi

    [[ -n "$vault_name" && "$vault_name" != "null" ]] || {
        err "Cannot determine Key Vault name. Has init run?"
        return 1
    }
    echo "$vault_name"
}

get_container_app_name() {
    az containerapp list \
        --resource-group "$RG" \
        --query "[0].name" \
        -o tsv 2>/dev/null || {
        err "Cannot determine Container App name. Has init run?"
        return 1
    }
}

get_cosmos_account_name() {
    az cosmosdb list \
        --resource-group "$RG" \
        --query "[0].name" \
        -o tsv 2>/dev/null || {
        err "Cannot determine Cosmos account name. Has init run?"
        return 1
    }
}

get_appinsights_name() {
    # `az monitor app-insights component show` requires --app, which
    # we don't know yet — it's the very thing we're trying to discover.
    # `az resource list` filtered by type works without --app.
    # Returns empty string if no App Insights component exists in the RG.
    az resource list \
        --resource-group "$RG" \
        --resource-type microsoft.insights/components \
        --query "[0].name" \
        -o tsv 2>/dev/null || echo ""
}

# ---------------------------------------------------------------------------
# Seed placeholder secrets in Key Vault.
#
# The Container App provisioning step in main.bicep validates that every
# secret named in `properties.configuration.secrets[].keyVaultUrl` exists
# at deploy time, even though the values won't be used until first
# request. So before running `az deployment group create`, every secret
# must exist (even as a placeholder).
#
# This function is safe to re-run — it skips secrets that already exist
# with any value (placeholder or real).
# ---------------------------------------------------------------------------
seed_placeholder_secrets() {
    local vault_name="$1"
    log "Seeding placeholder secrets in Key Vault '$vault_name'..."

    local count_existing=0
    local count_seeded=0

    for secret_name in "${SECRET_NAMES[@]}"; do
        # `az keyvault secret show` returns non-zero if the secret
        # doesn't exist. We use --query to suppress output.
        if az keyvault secret show \
            --vault-name "$vault_name" \
            --name "$secret_name" \
            --query "value" \
            -o tsv >/dev/null 2>&1; then
            count_existing=$((count_existing + 1))
        else
            az keyvault secret set \
                --vault-name "$vault_name" \
                --name "$secret_name" \
                --value "$PLACEHOLDER_VALUE" \
                --output none
            count_seeded=$((count_seeded + 1))
        fi
    done

    ok "Secrets: $count_existing already existed, $count_seeded newly seeded."
}

# ---------------------------------------------------------------------------
# Subcommand: init
# ---------------------------------------------------------------------------
cmd_init() {
    heading "INIT — First-time deployment"
    check_prereqs

    log "Resource group: $RG"
    log "Location: $LOCATION"

    # Ensure the resource group exists. `az group create` is idempotent.
    log "Ensuring resource group exists..."
    az group create \
        --name "$RG" \
        --location "$LOCATION" \
        --output none
    ok "Resource group ready."

    # Get the deployer principal ID. For interactive `az login`, this
    # is the user's object ID. For service principal logins (CI), this
    # is the SP's object ID. The Bicep parameter type is 'User' by
    # default; CI should override to 'ServicePrincipal'.
    log "Resolving deployer principal ID..."
    local principal_id
    principal_id=$(az ad signed-in-user show --query id -o tsv 2>/dev/null || true)
    if [[ -z "$principal_id" ]]; then
        # Likely running under a service principal — fall back to the
        # current SP's object ID via the access token.
        principal_id=$(az account show --query user.name -o tsv | xargs -I {} \
            az ad sp list --display-name {} --query "[0].id" -o tsv 2>/dev/null || true)
    fi
    [[ -n "$principal_id" ]] || {
        err "Cannot resolve deployer principal ID."
        exit 1
    }
    ok "Deployer principal: $principal_id"

    # If the Key Vault already exists from a prior deploy, seed
    # placeholder secrets BEFORE the Bicep deploy (so the Container
    # App's secret refs validate). If the vault doesn't exist yet,
    # we'll do this AFTER the first Bicep deploy creates it.
    local vault_name
    vault_name=$(get_vault_name 2>/dev/null || echo "")
    if [[ -n "$vault_name" ]]; then
        log "Existing Key Vault detected ('$vault_name'). Seeding placeholders..."
        seed_placeholder_secrets "$vault_name"
    else
        warn "No Key Vault yet — placeholder seeding will happen in two phases."
        warn "If this is a truly fresh deploy, the first Bicep run will FAIL"
        warn "at the Container App step. That's expected. The script will then"
        warn "seed placeholders and re-run Bicep automatically."
    fi

    # Run the Bicep deployment.
    local deploy_name="deploy-$(date +%Y%m%d-%H%M%S)"
    log "Running Bicep deployment ($deploy_name)..."
    if az deployment group create \
        --resource-group "$RG" \
        --template-file "$BICEP_FILE" \
        --parameters @"$PARAMS_FILE" \
        --parameters deployerPrincipalId="$principal_id" \
        --name "$deploy_name" \
        --output none 2>&1; then
        ok "Bicep deployment succeeded."
    else
        # Almost certainly the Container App secret-ref validation
        # failure. Recover: seed placeholders, retry Bicep.
        warn "First Bicep deploy failed (likely Container App secret refs)."
        warn "Recovering: seeding placeholders + retrying."
        vault_name=$(get_vault_name)
        seed_placeholder_secrets "$vault_name"
        deploy_name="deploy-retry-$(date +%Y%m%d-%H%M%S)"
        log "Retrying Bicep deployment ($deploy_name)..."
        az deployment group create \
            --resource-group "$RG" \
            --template-file "$BICEP_FILE" \
            --parameters @"$PARAMS_FILE" \
            --parameters deployerPrincipalId="$principal_id" \
            --name "$deploy_name" \
            --output none
        ok "Retry succeeded."
    fi

    cmd_status
}

# ---------------------------------------------------------------------------
# Subcommand: secrets
#
# Replaces all 6 placeholder secrets with real values.
# - User-provided: read from env vars (must be set)
# - Generated: ip-hash-salt (only if currently placeholder)
# - Fetched: cosmos + appinsights connection strings
#
# After updating, restarts the Container App so new values are picked up.
# ---------------------------------------------------------------------------
cmd_secrets() {
    heading "SECRETS — Populate real Key Vault values"
    check_prereqs

    local vault_name
    vault_name=$(get_vault_name)
    log "Target vault: $vault_name"

    # User-provided values. Fail loudly if missing.
    for env_var in GEMINI_API_KEY ADMIN_PASSWORD TURNSTILE_SECRET_KEY; do
        if [[ -z "${!env_var:-}" ]]; then
            err "Environment variable $env_var is not set."
            err "Provide values for all three before running 'secrets':"
            err "  export GEMINI_API_KEY=AIza..."
            err "  export ADMIN_PASSWORD='your-strong-password-here'"
            err "  export TURNSTILE_SECRET_KEY=0x4A..."
            exit 1
        fi
    done

    # Fetched values.
    log "Fetching Cosmos connection string..."
    local cosmos_account cosmos_conn
    cosmos_account=$(get_cosmos_account_name)
    cosmos_conn=$(az cosmosdb keys list \
        --name "$cosmos_account" \
        --resource-group "$RG" \
        --type connection-strings \
        --query "connectionStrings[0].connectionString" \
        -o tsv)
    [[ -n "$cosmos_conn" ]] || { err "Cosmos connection string fetch failed."; exit 1; }
    ok "Cosmos conn fetched (${#cosmos_conn} chars)."

    log "Fetching App Insights connection string..."
    local appinsights_name appinsights_conn
    appinsights_name=$(get_appinsights_name)
    if [[ -n "$appinsights_name" ]]; then
        appinsights_conn=$(az monitor app-insights component show \
            --app "$appinsights_name" \
            --resource-group "$RG" \
            --query "connectionString" \
            -o tsv)
        ok "App Insights conn fetched (${#appinsights_conn} chars)."
    else
        warn "App Insights not found. Leaving secret as placeholder."
        appinsights_conn=""
    fi

    # IP hash salt — generated once, kept stable across re-deploys so
    # existing rate-limit entries remain verifiable. Only generate a
    # new one if the secret is still the placeholder.
    local current_salt
    current_salt=$(az keyvault secret show \
        --vault-name "$vault_name" \
        --name ip-hash-salt \
        --query "value" \
        -o tsv 2>/dev/null || echo "")
    local new_salt
    if [[ "$current_salt" == "$PLACEHOLDER_VALUE" || -z "$current_salt" ]]; then
        new_salt=$(openssl rand -hex 32)
        log "Generated new IP hash salt (will set in vault)."
    else
        new_salt="$current_salt"
        log "Keeping existing IP hash salt (do NOT rotate or rate-limit hashes break)."
    fi

    # Apply all values. Use `--output none` to suppress per-call JSON
    # noise; rely on `set -e` to fail loudly on any single error.
    log "Writing 6 secrets to vault..."
    az keyvault secret set --vault-name "$vault_name" --name gemini-api-key            --value "$GEMINI_API_KEY"      --output none
    az keyvault secret set --vault-name "$vault_name" --name cosmos-connection-string  --value "$cosmos_conn"         --output none
    az keyvault secret set --vault-name "$vault_name" --name ip-hash-salt              --value "$new_salt"            --output none
    az keyvault secret set --vault-name "$vault_name" --name admin-password            --value "$ADMIN_PASSWORD"      --output none
    az keyvault secret set --vault-name "$vault_name" --name turnstile-secret-key      --value "$TURNSTILE_SECRET_KEY" --output none
    if [[ -n "$appinsights_conn" ]]; then
        az keyvault secret set --vault-name "$vault_name" --name appinsights-connection-string --value "$appinsights_conn" --output none
    fi
    ok "All secrets written."

    # Restart the Container App so new values are picked up. Container
    # Apps re-fetches secrets when a new revision is created. The least-
    # invasive trigger is to update a tag, which forces a new revision
    # without changing any meaningful config.
    log "Restarting Container App to pick up new secret values..."
    local ca_name
    ca_name=$(get_container_app_name)
    az containerapp update \
        --name "$ca_name" \
        --resource-group "$RG" \
        --set-env-vars "DEPLOY_SECRETS_VERSION=$(date +%s)" \
        --output none
    ok "Container App restart triggered."

    log "Secrets phase complete. Run './deploy.sh status' to verify."
}

# ---------------------------------------------------------------------------
# Subcommand: image
# ---------------------------------------------------------------------------
cmd_image() {
    local image_ref="${1:-}"
    if [[ -z "$image_ref" ]]; then
        err "Usage: ./deploy.sh image <image-ref>"
        err "Example: ./deploy.sh image ghcr.io/sarthakdixit/indian-robbery-rag:latest"
        exit 1
    fi

    heading "IMAGE — Update Container App image to $image_ref"
    check_prereqs

    local ca_name
    ca_name=$(get_container_app_name)
    log "Updating Container App '$ca_name' image..."
    az containerapp update \
        --name "$ca_name" \
        --resource-group "$RG" \
        --image "$image_ref" \
        --output none
    ok "Image updated. New revision provisioning..."

    log "Tail the latest revision's logs with:"
    log "  az containerapp logs show --name $ca_name --resource-group $RG --follow"
}

# ---------------------------------------------------------------------------
# Subcommand: all
# ---------------------------------------------------------------------------
cmd_all() {
    cmd_init
    cmd_secrets
}

# ---------------------------------------------------------------------------
# Subcommand: status
#
# Prints all useful endpoints from the last successful deployment so
# operators don't have to remember resource names.
# ---------------------------------------------------------------------------
cmd_status() {
    heading "STATUS"

    # List recent TOP-LEVEL deployments only. Top-level deployments
    # are the ones invoked by `az deployment group create` from
    # deploy.sh — they have outputs. Module deployments
    # (containerapps-deployment, keyvault-deployment, etc.) are
    # nested deployments invoked by Bicep's `module` blocks; they
    # have their OWN outputs but not the top-level summary we want.
    #
    # We filter by name prefix matching our deploy.sh convention
    # (`deploy-*`). If you run `az deployment group create` directly
    # with a different name, this filter won't match — adjust the
    # convention or expand the filter.
    az deployment group list \
        --resource-group "$RG" \
        --query "sort_by([?starts_with(name, 'deploy-') && properties.provisioningState=='Succeeded'], &properties.timestamp) | reverse(@)[:5].{name:name, time:properties.timestamp}" \
        -o table

    echo ""
    log "Endpoints from latest successful top-level deployment:"

    local outputs
    outputs=$(az deployment group list \
        --resource-group "$RG" \
        --query "sort_by([?starts_with(name, 'deploy-') && properties.provisioningState=='Succeeded'], &properties.timestamp) | reverse(@)[0].properties.outputs" \
        -o json)

    if [[ "$outputs" == "null" || -z "$outputs" ]]; then
        warn "No successful top-level deployments found in $RG. Has 'init' run?"
        warn "Note: 'top-level' means deployments invoked by deploy.sh,"
        warn "named 'deploy-*'. Module deployments (containerapps-deployment, etc.)"
        warn "don't expose the top-level outputs."
        return
    fi

    echo "$outputs" | python3 -c '
import json, sys
data = json.load(sys.stdin)
keys = ["backendFqdn", "staticWebAppUrl", "cosmosAccountName",
        "keyVaultName", "appInsightsName", "budgetName"]
for k in keys:
    v = data.get(k, {}).get("value", "(not set)")
    print(f"  {k:32s} = {v}")
'

    echo ""
    log "Container App revisions:"
    local ca_name
    ca_name=$(get_container_app_name 2>/dev/null || echo "")
    if [[ -n "$ca_name" ]]; then
        az containerapp revision list \
            --name "$ca_name" \
            --resource-group "$RG" \
            --query "[].{name:name, active:properties.active, replicas:properties.replicas, image:properties.template.containers[0].image, createdAt:properties.createdTime}" \
            -o table | head -5
    fi
}

# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------
case "${1:-help}" in
    init)    shift; cmd_init    "$@" ;;
    secrets) shift; cmd_secrets "$@" ;;
    image)   shift; cmd_image   "$@" ;;
    all)     shift; cmd_all     "$@" ;;
    status)  shift; cmd_status  "$@" ;;
    help|-h|--help) cmd_help ;;
    *)
        err "Unknown subcommand: $1"
        cmd_help
        ;;
esac