// Time-based UI thresholds. These match the cold-start UX strategy
// in AGENT-frontend.md §12.3 — see useLoadingStage hook.
export const COLD_START_MESSAGE_DELAY_MS = 3_000;
export const COLD_START_STILL_GOING_DELAY_MS = 10_000;

// Turnstile token lifetime (Cloudflare says ~5 min); refresh before
// it expires to avoid mid-submit rejection.
export const TURNSTILE_REFRESH_INTERVAL_MS = 240_000;

// localStorage keys. Centralized so a key rename is one change.
export const STORAGE_KEYS = {
  disclaimerAccepted: "robbery-rag:disclaimer-accepted",
  adminPassword: "robbery-rag:admin-password",
} as const;

// Demo questions for the landing page. Backend pre-population (FR-7)
// is deferred to Batch 8; for now these are just clickable suggestions.
export const DEMO_QUESTIONS: readonly string[] = [
  "What is robbery under BNS?",
  "How does robbery differ from theft?",
  "What is the punishment for dacoity?",
  "What is the difference between robbery and extortion?",
] as const;

// OOS-rejection fallback suggestions. Used if the backend doesn't
// provide its own (it usually does).
export const FALLBACK_SUGGESTIONS: readonly string[] = [
  "What is robbery under BNS?",
  "Difference between robbery and theft?",
  "Robbery punishment under section 392 IPC",
] as const;
