import { Clock } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";

type RateLimitPanelProps = {
  message: string;
};

/**
 * Shown when the backend returns 429 (rate_limit_exceeded). Friendly
 * explanation + suggestion to come back later. Doesn't try to show a
 * countdown because the backend uses calendar-day windows, not
 * sliding windows — the reset time is "next UTC midnight" which is
 * confusing to display directly.
 */
export function RateLimitPanel({ message }: RateLimitPanelProps) {
  return (
    <Alert variant="warning">
      <Clock className="h-4 w-4" />
      <AlertTitle>Daily limit reached</AlertTitle>
      <AlertDescription>
        <p>{message}</p>
        <p className="mt-2 text-xs">
          The limit resets daily. This protects the small free-tier API quota that
          backs this demo. Come back tomorrow, or contact the maintainer if you need
          extended access.
        </p>
      </AlertDescription>
    </Alert>
  );
}
