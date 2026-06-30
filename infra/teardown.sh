#!/usr/bin/env bash
# teardown.sh — Destroy the Azure resource group for indian-robbery-rag.
#
# THIS IS DESTRUCTIVE. Read the prompts before answering.
#
# USAGE:
#   ./teardown.sh           # interactive prompts, soft-delete intact
#   ./teardown.sh --purge   # also purge soft-deleted KV/Cosmos
#   ./teardown.sh --help
#
# WHAT GETS DELETED:
#   - The entire resource group: rg-robberyrag-dev (or value of $RG)
#   - All resources in it (Cosmos, Key Vault, Container App, etc.)
#   - The budget at RG scope
#
# WHAT SURVIVES BY DEFAULT (--purge moves these to immediate deletion):
#   - Key Vault: soft-deleted for 7 days (name reserved). To free the
#     name immediately: `az keyvault purge --name <vault-name>`
#   - Cosmos: soft-deleted for 90 days (name reserved). NO CLI purge
#     exists — names auto-release after 90 days.
#   - GitHub Actions OIDC federation: tied to the app registration,
#     not the resource group. Survives teardown.
#
# AFTER TEARDOWN, RE-DEPLOY VIA:
#   ./deploy.sh all
#   (Will recreate the RG and all resources.)

set -euo pipefail

readonly RG="${RG:-rg-robberyrag-dev}"

log()    { printf '\033[1;34m[teardown]\033[0m %s\n' "$*" >&2; }
warn()   { printf '\033[1;33m[teardown]\033[0m %s\n' "$*" >&2; }
err()    { printf '\033[1;31m[teardown]\033[0m %s\n' "$*" >&2; }
ok()     { printf '\033[1;32m[teardown]\033[0m %s\n' "$*" >&2; }

# ---------------------------------------------------------------------------
# Parse flags
# ---------------------------------------------------------------------------
PURGE_AFTER=false
for arg in "$@"; do
    case "$arg" in
        --purge) PURGE_AFTER=true ;;
        --help|-h)
            head -25 "$0" | grep -E '^#( |$)' | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *)
            err "Unknown flag: $arg"
            exit 1
            ;;
    esac
done

# ---------------------------------------------------------------------------
# Show what will be destroyed
# ---------------------------------------------------------------------------
log "Target resource group: $RG"

if ! az group show --name "$RG" --output none 2>/dev/null; then
    warn "Resource group '$RG' does not exist. Nothing to do."
    exit 0
fi

log "Listing resources in $RG..."
echo ""
az resource list --resource-group "$RG" \
    --query "[].{Name:name, Type:type, Location:location}" \
    -o table
echo ""

# Show budget separately — it's at /Microsoft.Consumption/budgets not
# in the main resource list under all API versions.
log "Budgets in $RG..."
az consumption budget list \
    --resource-group "$RG" \
    --query "[].{Name:name, Amount:amount, TimeGrain:timeGrain}" \
    -o table 2>/dev/null || warn "(unable to list budgets — RG may have none, that's fine)"
echo ""

# Vault name (for the purge step later)
VAULT_NAME=""
if vault_name=$(az keyvault list --resource-group "$RG" --query "[0].name" -o tsv 2>/dev/null); then
    VAULT_NAME="$vault_name"
fi

# ---------------------------------------------------------------------------
# Two confirmation prompts. The second requires typing the RG name
# (defeats accidental Enter-presses through the first prompt).
# ---------------------------------------------------------------------------
echo ""
warn "About to PERMANENTLY DELETE the resource group above."
warn "This action cannot be undone via the portal."
if [[ "$PURGE_AFTER" == "true" ]]; then
    warn "After delete, will ALSO purge soft-deleted Key Vault."
fi
echo ""
read -r -p "Proceed? Type 'yes' to continue: " confirm1
if [[ "$confirm1" != "yes" ]]; then
    log "Aborted."
    exit 0
fi

echo ""
read -r -p "Final confirmation: type the resource group name ($RG): " confirm2
if [[ "$confirm2" != "$RG" ]]; then
    err "Name did not match. Aborted."
    exit 1
fi

# ---------------------------------------------------------------------------
# Execute
# ---------------------------------------------------------------------------
echo ""
log "Deleting resource group $RG (--no-wait, runs in background)..."
az group delete --name "$RG" --yes --no-wait
ok "Delete initiated. Monitor with: az group show --name $RG  (returns 'NotFound' when done)"

if [[ "$PURGE_AFTER" == "true" && -n "$VAULT_NAME" ]]; then
    log "Waiting for RG delete to finish before purging vault (vault must be soft-deleted first)..."
    while az group show --name "$RG" --output none 2>/dev/null; do
        sleep 10
        log "  ...still deleting..."
    done
    ok "RG deleted."

    log "Purging soft-deleted Key Vault '$VAULT_NAME'..."
    if az keyvault purge --name "$VAULT_NAME" --output none 2>&1; then
        ok "Key Vault purged. Name '$VAULT_NAME' is immediately reusable."
    else
        warn "Vault purge failed. It may already have been purged, or the soft-delete entry hasn't propagated yet."
        warn "Retry manually: az keyvault purge --name $VAULT_NAME"
    fi
fi

echo ""
ok "Teardown complete. To re-deploy from scratch: ./infra/deploy.sh all"