import { Clock, Database } from "lucide-react";
import type { QueryResponse } from "@/api/schemas/query";
import { isOutOfScope } from "@/api/schemas/query";
import { CitationCard } from "./CitationCard";
import { DisclaimerBanner } from "@/components/disclaimer/DisclaimerBanner";
import { OutOfScopePanel } from "@/components/states/OutOfScopePanel";
import { Card, CardContent } from "@/components/ui/card";
import { formatLatency } from "@/lib/utils";

type AnswerDisplayProps = {
  response: QueryResponse;
  onSuggestionClick?: ((suggestion: string) => void) | undefined;
};

/**
 * Renders the result of a successful query. Branches between OOS
 * (suggestion panel) and the normal answer (markdown-like text +
 * citation cards + footer disclaimer).
 *
 * The answer is rendered as-is from the backend with `whitespace-pre-line`
 * to preserve paragraph breaks. No actual markdown rendering — the
 * backend prompt produces clean paragraph-separated prose.
 */
export function AnswerDisplay({ response, onSuggestionClick }: AnswerDisplayProps) {
  if (isOutOfScope(response)) {
    return (
      <OutOfScopePanel suggestions={response.suggestions} onSuggestionClick={onSuggestionClick} />
    );
  }

  return (
    <div className="space-y-6">
      <Card>
        <CardContent className="pt-6">
          <article
            className="whitespace-pre-line text-base leading-relaxed text-foreground"
            aria-label="Answer"
          >
            {response.answer}
          </article>

          <footer className="mt-6 flex flex-wrap items-center gap-4 border-t pt-4 text-xs text-muted-foreground">
            <span className="flex items-center gap-1.5">
              <Clock className="h-3.5 w-3.5" />
              {formatLatency(response.latency_ms)}
            </span>
            {response.cache_hit && (
              <span className="flex items-center gap-1.5">
                <Database className="h-3.5 w-3.5" />
                Cached answer
              </span>
            )}
            <span className="ml-auto font-mono">id: {response.request_id.slice(0, 8)}</span>
          </footer>
        </CardContent>
      </Card>

      {response.citations.length > 0 && (
        <section aria-label="Citations">
          <h2 className="mb-3 text-sm font-semibold text-muted-foreground">
            Citations ({response.citations.length})
          </h2>
          <ul className="space-y-2">
            {response.citations.map((c) => (
              <li key={c.index}>
                <CitationCard citation={c} />
              </li>
            ))}
          </ul>
        </section>
      )}

      <DisclaimerBanner />
    </div>
  );
}
