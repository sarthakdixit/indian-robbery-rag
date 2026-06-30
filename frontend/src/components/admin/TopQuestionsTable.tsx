import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { TopQuestionsResponse } from "@/api/schemas/admin";

type TopQuestionsTableProps = {
  data: TopQuestionsResponse;
};

export function TopQuestionsTable({ data }: TopQuestionsTableProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-lg">Top questions</CardTitle>
      </CardHeader>
      <CardContent>
        {data.items.length === 0 ? (
          <p className="text-sm text-muted-foreground">No queries yet.</p>
        ) : (
          <ol className="space-y-2">
            {data.items.map((item, idx) => (
              <li
                key={item.question}
                className="flex items-center justify-between gap-4 border-b py-2 last:border-b-0"
              >
                <span className="flex items-center gap-3 truncate">
                  <span className="w-6 text-xs tabular-nums text-muted-foreground">
                    {(idx + 1).toString()}.
                  </span>
                  <span className="truncate text-sm">{item.question}</span>
                </span>
                <span className="shrink-0 rounded-md bg-muted px-2 py-0.5 text-xs font-medium tabular-nums">
                  ×{item.count.toString()}
                </span>
              </li>
            ))}
          </ol>
        )}
      </CardContent>
    </Card>
  );
}
