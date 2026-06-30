import { useMutation } from "@tanstack/react-query";
import { apiClient, ApiCallFailed } from "@/api/client";
import type { QueryRequest, QueryResponse } from "@/api/schemas/query";
import type { ApiError } from "@/api/errors";

/**
 * Mutation hook for submitting a query. The mutation's `error` is
 * an `ApiError` (typed discriminated union) — HomePage branches on
 * `error.code` to render the right state panel.
 *
 * We throw the ApiError object directly (not an Error instance) because
 * TanStack Query passes whatever is thrown to the error state, and we
 * want consumers to read `.code` and `.message` as a typed union without
 * unwrapping. The only-throw-error lint rule is suppressed at each
 * throw site with a justification comment.
 */
export function useSubmitQuery() {
  return useMutation<QueryResponse, ApiError, QueryRequest>({
    mutationFn: async (input) => {
      try {
        return await apiClient.submitQuery(input);
      } catch (err) {
        if (err instanceof ApiCallFailed) {
          // eslint-disable-next-line @typescript-eslint/only-throw-error -- ApiError is the mutation's typed error union; TanStack Query treats this as the error payload, not as a JS exception consumer.
          throw err.apiError;
        }
        // eslint-disable-next-line @typescript-eslint/only-throw-error -- see above.
        throw {
          code: "internal_error",
          message: err instanceof Error ? err.message : "Unknown error",
        } satisfies ApiError;
      }
    },
    retry: false, // see AGENT-frontend.md §8.4
  });
}
