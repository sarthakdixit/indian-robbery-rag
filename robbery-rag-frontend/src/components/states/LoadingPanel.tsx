import { Loader2 } from "lucide-react";
import { useLoadingStage } from "@/hooks/useLoadingStage";
import { Card, CardContent } from "@/components/ui/card";

type LoadingPanelProps = {
  isPending: boolean;
};

/**
 * Loading state. After 3 seconds, switches to a cold-start message
 * explaining the wait. After 10 seconds, acknowledges that things
 * are still warming up — useful for the first request after the
 * container scaled to zero.
 */
export function LoadingPanel({ isPending }: LoadingPanelProps) {
  const stage = useLoadingStage(isPending);

  if (!isPending) return null;

  return (
    <Card>
      <CardContent className="flex flex-col items-center gap-3 py-12 text-center">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" aria-hidden />
        <p className="text-sm font-medium" aria-live="polite">
          {stageMessage(stage)}
        </p>
        {stage === "cold-start" || stage === "still-going" ? (
          <p className="max-w-sm text-xs text-muted-foreground">
            The backend may be cold-starting. Subsequent queries are typically much
            faster.
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}

function stageMessage(stage: ReturnType<typeof useLoadingStage>): string {
  switch (stage) {
    case "idle":
      return "";
    case "spinner":
      return "Thinking...";
    case "cold-start":
      return "Still working — first requests can take a moment.";
    case "still-going":
      return "Hang on, we're getting there...";
  }
}
