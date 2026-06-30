import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

/**
 * Tailwind-aware className composer. Resolves conflicts between
 * conditionally-applied utility classes (e.g., `bg-red-500` overriding
 * `bg-blue-500`).
 *
 * @example
 * cn("rounded p-4", isError && "bg-destructive", "p-8")
 * // => "rounded bg-destructive p-8" (p-8 wins over p-4)
 */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

/** Format a number of milliseconds as human-readable latency. */
export function formatLatency(ms: number): string {
  if (ms < 1) return "<1ms";
  if (ms < 1000) return `${Math.round(ms).toString()}ms`;
  return `${(ms / 1000).toFixed(2)}s`;
}

/** Format USD cents as a currency string. Used in the admin dashboard. */
export function formatCostUsd(usd: number): string {
  if (usd === 0) return "$0.00";
  if (usd < 0.01) return `$${(usd * 1000).toFixed(2)}m`; // millicents
  return `$${usd.toFixed(4)}`;
}
