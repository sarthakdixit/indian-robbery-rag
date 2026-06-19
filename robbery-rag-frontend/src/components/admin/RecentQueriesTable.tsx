import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { ChevronLeft, ChevronRight } from "lucide-react";
import type { RecentQueriesResponse } from "@/api/schemas/admin";
import { formatLatency, formatCostUsd } from "@/lib/utils";

type RecentQueriesTableProps = {
  data: RecentQueriesResponse;
  page: number;
  pageSize: number;
  onPageChange: (page: number) => void;
};

export function RecentQueriesTable({
  data,
  page,
  pageSize,
  onPageChange,
}: RecentQueriesTableProps) {
  const totalPages = Math.max(1, Math.ceil(data.total / pageSize));
  const canGoPrev = page > 0;
  const canGoNext = (page + 1) * pageSize < data.total;

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle className="text-lg">Recent queries</CardTitle>
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <span>
            Page {(page + 1).toString()} / {totalPages.toString()}
          </span>
          <Button
            size="icon"
            variant="ghost"
            onClick={() => {
              onPageChange(page - 1);
            }}
            disabled={!canGoPrev}
            aria-label="Previous page"
          >
            <ChevronLeft className="h-4 w-4" />
          </Button>
          <Button
            size="icon"
            variant="ghost"
            onClick={() => {
              onPageChange(page + 1);
            }}
            disabled={!canGoNext}
            aria-label="Next page"
          >
            <ChevronRight className="h-4 w-4" />
          </Button>
        </div>
      </CardHeader>
      <CardContent>
        {data.items.length === 0 ? (
          <p className="text-sm text-muted-foreground">No queries in this range.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-left text-xs uppercase text-muted-foreground">
                  <th className="py-2 pr-4">Time (UTC)</th>
                  <th className="py-2 pr-4">IP</th>
                  <th className="py-2 pr-4">Question</th>
                  <th className="py-2 pr-4">Status</th>
                  <th className="py-2 pr-4 text-right">Latency</th>
                  <th className="py-2 text-right">Cost</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((item) => (
                  <tr key={item.request_id} className="border-b last:border-b-0">
                    <td className="py-2 pr-4 font-mono text-xs">
                      {item.timestamp_utc.slice(11, 19)}
                    </td>
                    <td className="py-2 pr-4 font-mono text-xs text-muted-foreground">
                      {item.hashed_ip_short}
                    </td>
                    <td className="max-w-md truncate py-2 pr-4">{item.question}</td>
                    <td className="py-2 pr-4">
                      {item.rejected ? (
                        <span className="text-amber-600">Rejected</span>
                      ) : item.cache_hit ? (
                        <span className="text-muted-foreground">Cached</span>
                      ) : (
                        <span className="text-emerald-600">OK</span>
                      )}
                    </td>
                    <td className="py-2 pr-4 text-right tabular-nums">
                      {formatLatency(item.latency_ms)}
                    </td>
                    <td className="py-2 text-right tabular-nums">
                      {formatCostUsd(item.estimated_cost_usd)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
