import { useState } from "react";
import { Sparkles } from "lucide-react";
import { QueryBox } from "@/components/query/QueryBox";
import { AnswerDisplay } from "@/components/query/AnswerDisplay";
import { LoadingPanel } from "@/components/states/LoadingPanel";
import { RateLimitPanel } from "@/components/states/RateLimitPanel";
import { GenericErrorPanel } from "@/components/states/GenericErrorPanel";
import { useSubmitQuery } from "@/hooks/useSubmitQuery";
import { Button } from "@/components/ui/button";
import { DEMO_QUESTIONS } from "@/config/constants";
import type { QueryRequest } from "@/api/schemas/query";

/**
 * Landing page. Pre-filled demo question buttons at the top to
 * encourage exploration; the QueryBox below; then whichever state
 * panel matches the current mutation status.
 *
 * The `initialQuestion` state is what flows from "click demo button"
 * → QueryBox textarea. Submission goes through useSubmitQuery, whose
 * `mutate` triggers either AnswerDisplay (success/OOS) or an error
 * panel branched by the typed ApiError code.
 */
export function HomePage() {
  const [seedQuestion, setSeedQuestion] = useState<string>("");
  const submit = useSubmitQuery();

  const handleSubmit = (input: QueryRequest): void => {
    submit.mutate(input);
  };

  const handleDemoClick = (q: string): void => {
    setSeedQuestion(q);
  };

  return (
    <div className="container max-w-3xl space-y-8 py-8">
      <section>
        <h1 className="mb-2 text-3xl font-bold tracking-tight sm:text-4xl">
          Robbery Law Research Assistant
        </h1>
        <p className="text-muted-foreground">
          Ask a question about Indian robbery offences — BNS §§309-311 (2023) or
          IPC §§390-402 (1860). Every answer is grounded in cited statutes and
          High Court / Supreme Court judgments.
        </p>
      </section>

      <section aria-label="Demo questions">
        <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold text-muted-foreground">
          <Sparkles className="h-3.5 w-3.5" />
          Try one of these:
        </h2>
        <div className="flex flex-wrap gap-2">
          {DEMO_QUESTIONS.map((q) => (
            <Button
              key={q}
              variant="outline"
              size="sm"
              onClick={() => {
                handleDemoClick(q);
              }}
            >
              {q}
            </Button>
          ))}
        </div>
      </section>

      <section>
        <QueryBox
          onSubmit={handleSubmit}
          isPending={submit.isPending}
          initialQuestion={seedQuestion}
        />
      </section>

      <section aria-live="polite" aria-busy={submit.isPending}>
        {submit.isPending && <LoadingPanel isPending={submit.isPending} />}

        {submit.isError && submit.error.code === "rate_limit_exceeded" && (
          <RateLimitPanel message={submit.error.message} />
        )}

        {submit.isError && submit.error.code !== "rate_limit_exceeded" && (
          <GenericErrorPanel error={submit.error} />
        )}

        {submit.isSuccess && (
          <AnswerDisplay
            response={submit.data}
            onSuggestionClick={(s) => {
              setSeedQuestion(s);
            }}
          />
        )}
      </section>
    </div>
  );
}
