import { AlertOctagon } from "lucide-react";
import type { FallbackProps } from "react-error-boundary";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";

/**
 * Top-level error boundary fallback. Catches any uncaught React
 * render error and shows a recoverable panel rather than a white
 * screen of death. Wired in App.tsx via react-error-boundary.
 */
export function AppErrorFallback({ error, resetErrorBoundary }: FallbackProps) {
  return (
    <div className="container py-12">
      <Alert variant="destructive">
        <AlertOctagon className="h-4 w-4" />
        <AlertTitle>Something broke</AlertTitle>
        <AlertDescription>
          <p className="mb-3">
            The page hit an unexpected error. This isn't supposed to happen — if you can reproduce
            it, please open an issue.
          </p>
          <details className="text-xs">
            <summary className="cursor-pointer">Technical detail</summary>
            <pre className="mt-2 whitespace-pre-wrap rounded bg-muted p-2">
              {error instanceof Error ? error.message : String(error)}
            </pre>
          </details>
          <Button onClick={resetErrorBoundary} className="mt-4" size="sm">
            Try again
          </Button>
        </AlertDescription>
      </Alert>
    </div>
  );
}
