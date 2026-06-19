import { AlertTriangle } from "lucide-react";

/**
 * Shown at the foot of every answer. Short, lo-fi reminder — the
 * full legal text lives on /terms and is gated behind the first-visit
 * modal. AGENT-frontend.md §13.1 spells this out as a hard requirement.
 */
export function DisclaimerBanner() {
  return (
    <div
      role="note"
      className="flex items-start gap-2 rounded-md border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900 dark:border-amber-900/50 dark:bg-amber-950/30 dark:text-amber-200"
    >
      <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
      <p>
        AI-generated answer for research only. Not legal advice. Verify against
        cited sources before relying on anything here.
      </p>
    </div>
  );
}
