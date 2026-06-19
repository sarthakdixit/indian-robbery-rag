import { Compass } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { FALLBACK_SUGGESTIONS } from "@/config/constants";

type OutOfScopePanelProps = {
  suggestions?: string[] | undefined;
  onSuggestionClick?: ((suggestion: string) => void) | undefined;
};

/**
 * Shown when the retriever's vector similarity is below the
 * scope threshold (0.60). Tells the user this assistant is
 * narrow on purpose, then offers in-scope alternatives.
 */
export function OutOfScopePanel({ suggestions, onSuggestionClick }: OutOfScopePanelProps) {
  const shown =
    suggestions !== undefined && suggestions.length > 0 ? suggestions : FALLBACK_SUGGESTIONS;

  return (
    <Alert>
      <Compass className="h-4 w-4" />
      <AlertTitle>That looks out of scope</AlertTitle>
      <AlertDescription>
        <p>
          This assistant only covers <strong>robbery offences under Indian criminal
          law</strong> (BNS §§309-311 or IPC §§390-402). Try one of these instead:
        </p>
        <ul className="mt-3 space-y-2">
          {shown.map((s) => (
            <li key={s}>
              <Button
                variant="outline"
                size="sm"
                onClick={() => onSuggestionClick?.(s)}
                disabled={onSuggestionClick === undefined}
              >
                {s}
              </Button>
            </li>
          ))}
        </ul>
      </AlertDescription>
    </Alert>
  );
}
