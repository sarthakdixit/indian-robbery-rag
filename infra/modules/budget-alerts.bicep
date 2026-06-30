// Budget + email alert notifications module.
//
// SCOPE: Resource Group (same as the rest of the stack). All resources
// in this RG count toward the budget; resources outside (other projects)
// do not. This matches design.md NFR-1 ("target Rs 500/month") which is
// for this project alone.
//
// FOUR THRESHOLDS, MIXED FORECASTED + ACTUAL:
//
//   50% Forecasted — heads-up. Cosmos is mostly idle, traffic is
//                    sparse, but at the halfway mark by spend trend
//                    it's worth noticing.
//   75% Forecasted — concerning. Cost is trending toward the cap.
//                    Time to investigate before the meter actually
//                    hits 75%.
//   90% Actual     — urgent. Real spend has reached 90% of cap.
//                    Investigate THIS month's usage; identify the
//                    largest cost contributor.
//   100% Actual    — cap reached. Decision point: keep running
//                    (knowing you'll exceed) or trigger the manual
//                    kill switch (infra/manual-kill-switch.md).
//
// Auto-stop runbook is INTENTIONALLY NOT included — see design.md AP-7
// and the note in main.bicep. Manual kill switch is the recovery path,
// documented for the operator.
//
// CURRENCY: subscription billing currency. For Indian subscriptions
// this is INR; amount=500 means ₹500/month. The Azure portal displays
// the currency symbol automatically. No currency field exists in the
// API — it's inferred from the subscription.
//
// EMAIL DELIVERY: Azure typically sends within an hour of evaluation.
// Cost data refresh is every 8-24 hours per docs, so the lag between
// a spike and the email can be 24+ hours. This is fine for our
// purposes (we're protecting a monthly budget, not preventing a
// minute-by-minute runaway).
//
// IDEMPOTENCY: budget name is fixed (not derived from a hash). Re-
// deploying with the same name updates the existing budget in place.
// Deleting requires `az consumption budget delete`.

// ============================================================================
// Parameters
// ============================================================================

@description('Budget name. Must be unique within the resource group. Alphanumeric, underscore, hyphen.')
@minLength(1)
@maxLength(63)
param budgetName string = 'robberyrag-monthly-budget'

@description('Budget amount in subscription billing currency. For Indian subscriptions this is INR. Design target is ₹500/month.')
@minValue(1)
param amount int = 500

@description('Time grain. Monthly is the only sensible choice for this project; Quarterly/Annually defeat the point of an early-warning budget.')
@allowed([
  'Monthly'
  'Quarterly'
  'Annually'
])
param timeGrain string = 'Monthly'

@description('Budget start date. Must be the FIRST day of a month in YYYY-MM-DD format. Past dates allowed within the current period; future dates limited to 3 months ahead. Update this if deploying many months after writing this file — the default may be too far in the past for Azure to accept.')
param startDate string = '2026-06-01'

@description('Optional end date in YYYY-MM-DD format. Defaults to 10 years from startDate if omitted. We default explicitly to keep deploys deterministic.')
param endDate string = '2036-06-01'

@description('Email address(es) to notify on threshold breach. Comma-separated values allowed via Bicep array. design.md AP-6 calls for human-recipient alerts.')
param notificationEmails array = [
  'sarthak_dixit@outlook.com'
]

// ============================================================================
// Resources
// ============================================================================

// Budget with 4 threshold notifications. The notifications block is a
// keyed dictionary, NOT an array — each key is the unique notification
// name and the value is the config. Naming convention:
//   <ThresholdType>_<Operator>_<Percent>_Percent
// This convention is what the Azure portal uses internally; the keys
// could be arbitrary strings but matching the portal's naming makes
// debugging easier (the portal UI shows these names).
resource budget 'Microsoft.Consumption/budgets@2024-08-01' = {
  name: budgetName
  properties: {
    category: 'Cost'
    amount: amount
    timeGrain: timeGrain
    timePeriod: {
      startDate: startDate
      endDate: endDate
    }
    // No `filter` block — we want ALL costs in this resource group
    // to count toward the budget. Filtering would scope to specific
    // resources, services, or tags; we want everything.
    notifications: {
      // 50% Forecasted — early heads-up while there's still time to
      // course-correct in the same month.
      Forecasted_GreaterThan_50_Percent: {
        enabled: true
        operator: 'GreaterThan'
        threshold: 50
        thresholdType: 'Forecasted'
        contactEmails: notificationEmails
        contactRoles: []
        contactGroups: []
      }
      // 75% Forecasted — concerning. Cost is on a trajectory to
      // exceed budget; act NOW.
      Forecasted_GreaterThan_75_Percent: {
        enabled: true
        operator: 'GreaterThan'
        threshold: 75
        thresholdType: 'Forecasted'
        contactEmails: notificationEmails
        contactRoles: []
        contactGroups: []
      }
      // 90% Actual — urgent. Money has already been spent.
      Actual_GreaterThan_90_Percent: {
        enabled: true
        operator: 'GreaterThan'
        threshold: 90
        thresholdType: 'Actual'
        contactEmails: notificationEmails
        contactRoles: []
        contactGroups: []
      }
      // 100% Actual — cap reached. Open infra/manual-kill-switch.md.
      Actual_GreaterThan_100_Percent: {
        enabled: true
        operator: 'GreaterThan'
        threshold: 100
        thresholdType: 'Actual'
        contactEmails: notificationEmails
        contactRoles: []
        contactGroups: []
      }
    }
  }
}

// ============================================================================
// Outputs
// ============================================================================

@description('Budget resource ID — useful for `az consumption budget show/delete`.')
output budgetResourceId string = budget.id

@description('Budget name — input to `az consumption budget show --budget-name ...`.')
output budgetName string = budget.name

// NOTE: We do NOT expose budgetAmount as an output. ARM returns the
// amount as a Float, not an Int (even though we declared `amount int`
// in params), which causes "Expected Integer, received Float" output
// evaluation errors. The amount is recoverable any time via:
//   az consumption budget show --budget-name <name> -g <rg> --query amount -o tsv