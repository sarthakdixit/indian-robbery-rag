import { useEffect, useState } from "react";
import { COLD_START_MESSAGE_DELAY_MS, COLD_START_STILL_GOING_DELAY_MS } from "@/config/constants";

export type LoadingStage = "idle" | "spinner" | "cold-start" | "still-going";

/**
 * Emits a UX stage based on how long the current request has been
 * pending. Used by the answer panel to swap a subtle spinner for a
 * cold-start explanation after 3 seconds, then a "still warming up"
 * message after 10 seconds.
 *
 * AGENT-frontend.md §12.3 specifies these thresholds.
 */
export function useLoadingStage(isPending: boolean): LoadingStage {
  const [stage, setStage] = useState<LoadingStage>("idle");

  useEffect(() => {
    if (!isPending) {
      setStage("idle");
      return;
    }
    setStage("spinner");
    const t1 = window.setTimeout(() => {
      setStage("cold-start");
    }, COLD_START_MESSAGE_DELAY_MS);
    const t2 = window.setTimeout(() => {
      setStage("still-going");
    }, COLD_START_STILL_GOING_DELAY_MS);
    return () => {
      window.clearTimeout(t1);
      window.clearTimeout(t2);
    };
  }, [isPending]);

  return stage;
}
