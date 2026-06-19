import { AlertOctagon, WifiOff } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import type { ApiError } from "@/api/errors";

type GenericErrorPanelProps = {
  error: ApiError;
};

/**
 * Catch-all for any ApiError code we don't have a dedicated panel
 * for. Switches the icon and copy based on the code so the user
 * sees something helpful rather than "Error: turnstile_failed".
 */
export function GenericErrorPanel({ error }: GenericErrorPanelProps) {
  const { Icon, title, description } = describe(error);

  return (
    <Alert variant="destructive">
      <Icon className="h-4 w-4" />
      <AlertTitle>{title}</AlertTitle>
      <AlertDescription>
        <p>{description}</p>
        <p className="mt-2 text-xs opacity-80">{error.message}</p>
      </AlertDescription>
    </Alert>
  );
}

function describe(error: ApiError): {
  Icon: typeof AlertOctagon;
  title: string;
  description: string;
} {
  switch (error.code) {
    case "network_error":
      return {
        Icon: WifiOff,
        title: "Can't reach the backend",
        description:
          "Check that the backend is running on http://localhost:8000 (or your configured VITE_API_BASE_URL).",
      };
    case "turnstile_failed":
      return {
        Icon: AlertOctagon,
        title: "Bot check failed",
        description:
          "Cloudflare didn't accept the verification. Try refreshing the page.",
      };
    case "demo_at_capacity":
      return {
        Icon: AlertOctagon,
        title: "Demo capacity reached",
        description:
          "We've hit the daily quota for the free demo. Try again tomorrow.",
      };
    case "llm_unavailable":
      return {
        Icon: AlertOctagon,
        title: "AI model temporarily unavailable",
        description:
          "Gemini didn't respond. This is usually transient — please try again in a moment.",
      };
    case "invalid_query":
      return {
        Icon: AlertOctagon,
        title: "Invalid query",
        description: "The request didn't pass validation.",
      };
    case "citation_verification_failed":
      return {
        Icon: AlertOctagon,
        title: "Couldn't verify citations",
        description:
          "The model returned an answer, but its citations didn't match the retrieved sources. We've discarded it for safety.",
      };
    case "rate_limit_exceeded":
    case "out_of_scope":
    case "admin_auth_failed":
    case "internal_error":
      return {
        Icon: AlertOctagon,
        title: "Something went wrong",
        description: "Please try again. If this keeps happening, contact the maintainer.",
      };
  }
}
