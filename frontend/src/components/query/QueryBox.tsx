import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { Send } from "lucide-react";
import { QueryRequestSchema, type QueryRequest } from "@/api/schemas/query";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { TurnstileWidget } from "./TurnstileWidget";
import { cn } from "@/lib/utils";

type QueryBoxProps = {
  onSubmit: (input: QueryRequest) => void;
  isPending: boolean;
  initialQuestion?: string | undefined;
};

/**
 * The main query input. Form state via React Hook Form, schema
 * validation via Zod, anti-bot via Turnstile.
 *
 * The Turnstile widget runs alongside the textarea; the submit
 * button stays disabled until both (a) the question is valid
 * and (b) Turnstile has produced a token.
 */
export function QueryBox({ onSubmit, isPending, initialQuestion }: QueryBoxProps) {
  const [turnstileToken, setTurnstileToken] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    formState: { errors, isValid },
    setValue,
  } = useForm<Omit<QueryRequest, "turnstile_token">>({
    resolver: zodResolver(QueryRequestSchema.omit({ turnstile_token: true })),
    mode: "onChange",
    defaultValues: { question: initialQuestion ?? "" },
  });

  // Sync from parent when a demo button is clicked. useEffect (not
  // inline render-time state mutation) avoids infinite render loops
  // — RHF's setValue triggers a re-render, which would re-fire the
  // mutation if it lived in the render body.
  useEffect(() => {
    if (initialQuestion !== undefined && initialQuestion !== "") {
      setValue("question", initialQuestion, { shouldValidate: true });
    }
  }, [initialQuestion, setValue]);

  const canSubmit = isValid && turnstileToken !== null && !isPending;

  const onFormSubmit = handleSubmit((data) => {
    if (turnstileToken === null) return;
    onSubmit({ question: data.question, turnstile_token: turnstileToken });
  });

  return (
    <form onSubmit={onFormSubmit} className="space-y-4">
      <div>
        <label htmlFor="question" className="sr-only">
          Your question
        </label>
        <Textarea
          id="question"
          rows={4}
          placeholder="Ask a question about Indian robbery law (BNS §§309-311 or IPC §§390-402)..."
          aria-invalid={errors.question !== undefined}
          aria-describedby={errors.question !== undefined ? "question-error" : undefined}
          disabled={isPending}
          {...register("question")}
        />
        {errors.question?.message !== undefined && (
          <p
            id="question-error"
            role="alert"
            className="mt-1.5 text-sm text-destructive"
          >
            {errors.question.message}
          </p>
        )}
      </div>

      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-h-[65px] flex-grow">
          <TurnstileWidget
            onVerify={setTurnstileToken}
            onExpire={() => {
              setTurnstileToken(null);
            }}
            onError={() => {
              setTurnstileToken(null);
            }}
          />
        </div>
        <Button
          type="submit"
          size="lg"
          disabled={!canSubmit}
          className={cn("sm:w-auto", "min-w-[140px]")}
        >
          <Send className="h-4 w-4" />
          {isPending ? "Thinking..." : "Ask"}
        </Button>
      </div>
    </form>
  );
}
