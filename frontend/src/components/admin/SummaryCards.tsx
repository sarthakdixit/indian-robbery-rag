import { Card, CardContent } from "@/components/ui/card";
import type { SummaryResponse } from "@/api/schemas/admin";
import { formatCostUsd, formatLatency } from "@/lib/utils";

type SummaryCardsProps = {
  summary: SummaryResponse;
};

function pct(n: number): string {
  return `${(n * 100).toFixed(1)}%`;
}

export function SummaryCards({ summary }: SummaryCardsProps) {
  const tiles = [
    { label: "Queries", value: summary.total_queries.toString() },
    {
      label: "Success / Rejection",
      value: `${summary.total_successes.toString()} / ${summary.total_rejections.toString()}`,
      sub: pct(summary.rejection_rate) + " rejected",
    },
    {
      label: "Cache hit rate",
      value: pct(summary.cache_hit_rate),
      sub: `${summary.total_cache_hits.toString()} hits`,
    },
    {
      label: "Latency (p50 / p95)",
      value:
        summary.p50_latency_ms !== null
          ? `${formatLatency(summary.p50_latency_ms)} / ${formatLatency(summary.p95_latency_ms ?? 0)}`
          : "—",
    },
    {
      label: "Est. cost",
      value: formatCostUsd(summary.total_estimated_cost_usd),
      sub: `${summary.window_start} → ${summary.window_end}`,
    },
  ];

  return (
    <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-5">
      {tiles.map((tile) => (
        <li key={tile.label}>
          <Card>
            <CardContent className="pt-6">
              <p className="text-xs uppercase tracking-wide text-muted-foreground">
                {tile.label}
              </p>
              <p className="mt-1 text-2xl font-semibold tabular-nums">{tile.value}</p>
              {tile.sub !== undefined && (
                <p className="mt-1 text-xs text-muted-foreground">{tile.sub}</p>
              )}
            </CardContent>
          </Card>
        </li>
      ))}
    </ul>
  );
}
