import { useMutation } from "@tanstack/react-query";
import { apiClient, ApiCallFailed } from "@/api/client";
import type { QueryRequest, QueryResponse } from "@/api/schemas/query";
import type { ApiError } from "@/api/errors";

/**
 * Mutation hook for submitting a query. The mutation's `error` is
 * an `ApiError` (typed discriminated union) — wrap unwraps the
 * ApiCallFailed exception.
 */
export function useSubmitQuery() {
  return useMutation<QueryResponse, ApiError, QueryRequest>({
    mutationFn: async (input) => {
      try {
        return await apiClient.submitQuery(input);
      } catch (err) {
        if (err instanceof ApiCallFailed) {
          throw err.apiError;
        }
        throw {
          code: "internal_error",
          message: err instanceof Error ? err.message : "Unknown error",
        } satisfies ApiError;
      }
    },
    retry: false, // see AGENT-frontend.md §8.4
  });
}
