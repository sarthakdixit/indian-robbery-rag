import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { LogOut } from "lucide-react";
import { useAdminAuthStore } from "@/stores/useAdminAuthStore";
import { apiClient, ApiCallFailed } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import { AdminLogin } from "@/components/admin/AdminLogin";
import { SummaryCards } from "@/components/admin/SummaryCards";
import { TopQuestionsTable } from "@/components/admin/TopQuestionsTable";
import { RecentQueriesTable } from "@/components/admin/RecentQueriesTable";
import { Button } from "@/components/ui/button";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";

const PAGE_SIZE = 20;

export function AdminPage() {
  const password = useAdminAuthStore((s) => s.password);
  const clear = useAdminAuthStore((s) => s.clear);
  const [page, setPage] = useState(0);

  // Only query when we have a password; the `enabled` flag keeps
  // TanStack Query from firing before login.
  const summaryQuery = useQuery({
    queryKey: queryKeys.admin.summary(),
    queryFn: () => apiClient.getAdminSummary(password ?? ""),
    enabled: password !== null,
    retry: false,
  });

  const topQuery = useQuery({
    queryKey: queryKeys.admin.topQuestions(10),
    queryFn: () => apiClient.getTopQuestions(password ?? "", 10),
    enabled: password !== null,
    retry: false,
  });

  const recentQuery = useQuery({
    queryKey: queryKeys.admin.recentQueries(PAGE_SIZE, page * PAGE_SIZE),
    queryFn: () => apiClient.getRecentQueries(password ?? "", PAGE_SIZE, page * PAGE_SIZE),
    enabled: password !== null,
    retry: false,
  });

  if (password === null) {
    return (
      <div className="container py-12">
        <AdminLogin />
      </div>
    );
  }

  // Detect auth failure mid-session (e.g., password was rotated server-side).
  const authFailed =
    (summaryQuery.error instanceof ApiCallFailed &&
      summaryQuery.error.apiError.code === "admin_auth_failed") ||
    (topQuery.error instanceof ApiCallFailed &&
      topQuery.error.apiError.code === "admin_auth_failed") ||
    (recentQuery.error instanceof ApiCallFailed &&
      recentQuery.error.apiError.code === "admin_auth_failed");

  if (authFailed) {
    clear();
    return (
      <div className="container py-12">
        <Alert variant="destructive">
          <AlertTitle>Session expired</AlertTitle>
          <AlertDescription>Please log in again.</AlertDescription>
        </Alert>
      </div>
    );
  }

  return (
    <div className="container space-y-6 py-8">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Admin dashboard</h1>
        <Button variant="ghost" size="sm" onClick={clear}>
          <LogOut className="h-4 w-4" />
          Log out
        </Button>
      </div>

      {summaryQuery.isPending && <p className="text-sm text-muted-foreground">Loading...</p>}

      {summaryQuery.isSuccess && <SummaryCards summary={summaryQuery.data} />}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {topQuery.isSuccess && <TopQuestionsTable data={topQuery.data} />}

        {recentQuery.isSuccess && (
          <RecentQueriesTable
            data={recentQuery.data}
            page={page}
            pageSize={PAGE_SIZE}
            onPageChange={setPage}
          />
        )}
      </div>
    </div>
  );
}
