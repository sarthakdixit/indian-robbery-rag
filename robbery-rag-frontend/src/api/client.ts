import { z } from "zod";
import { env } from "@/config/env";
import {
  type QueryRequest,
  type QueryResponse,
  QueryResponseSchema,
} from "./schemas/query";
import {
  type SummaryResponse,
  SummaryResponseSchema,
  type TopQuestionsResponse,
  TopQuestionsResponseSchema,
  type RecentQueriesResponse,
  RecentQueriesResponseSchema,
} from "./schemas/admin";
import { apiErrorFromBody, networkError, type ApiError } from "./errors";

/**
 * Thrown when the API returns a non-OK response or the response body
 * doesn't match the expected schema. The TanStack Query layer catches
 * this and exposes the typed `apiError` on the error state.
 */
export class ApiCallFailed extends Error {
  constructor(public readonly apiError: ApiError) {
    super(apiError.message);
    this.name = "ApiCallFailed";
  }
}

export class ApiClient {
  constructor(private readonly baseUrl: string = env.VITE_API_BASE_URL) {}

  // -------------------------------------------------------------------
  // Public endpoints
  // -------------------------------------------------------------------

  async submitQuery(input: QueryRequest): Promise<QueryResponse> {
    return this.postJson("/api/query", input, QueryResponseSchema);
  }

  async getHealth(): Promise<{ status: string; uptime_seconds: number }> {
    return this.getJson(
      "/api/health",
      {},
      z.object({ status: z.string(), uptime_seconds: z.number() }),
    );
  }

  // -------------------------------------------------------------------
  // Admin endpoints — every call needs the x-admin-password header
  // -------------------------------------------------------------------

  async getAdminSummary(password: string, days?: number): Promise<SummaryResponse> {
    const path = days !== undefined ? `/api/admin/summary?days=${days}` : "/api/admin/summary";
    return this.getJson(path, { "x-admin-password": password }, SummaryResponseSchema);
  }

  async getTopQuestions(password: string, limit = 10): Promise<TopQuestionsResponse> {
    return this.getJson(
      `/api/admin/top-questions?limit=${limit}`,
      { "x-admin-password": password },
      TopQuestionsResponseSchema,
    );
  }

  async getRecentQueries(
    password: string,
    limit = 50,
    offset = 0,
  ): Promise<RecentQueriesResponse> {
    return this.getJson(
      `/api/admin/recent-queries?limit=${limit}&offset=${offset}`,
      { "x-admin-password": password },
      RecentQueriesResponseSchema,
    );
  }

  // -------------------------------------------------------------------
  // Internals
  // -------------------------------------------------------------------

  private async getJson<T>(
    path: string,
    headers: Record<string, string>,
    schema: z.ZodSchema<T>,
  ): Promise<T> {
    let response: Response;
    try {
      response = await fetch(`${this.baseUrl}${path}`, { method: "GET", headers });
    } catch (err) {
      throw new ApiCallFailed(networkError(err instanceof Error ? err.message : "unknown"));
    }
    return this.handleResponse(response, schema);
  }

  private async postJson<T>(
    path: string,
    body: unknown,
    schema: z.ZodSchema<T>,
  ): Promise<T> {
    let response: Response;
    try {
      response = await fetch(`${this.baseUrl}${path}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
    } catch (err) {
      throw new ApiCallFailed(networkError(err instanceof Error ? err.message : "unknown"));
    }
    return this.handleResponse(response, schema);
  }

  private async handleResponse<T>(response: Response, schema: z.ZodSchema<T>): Promise<T> {
    let body: unknown;
    try {
      body = await response.json();
    } catch {
      throw new ApiCallFailed({
        code: "internal_error",
        message: `Non-JSON response (HTTP ${response.status.toString()})`,
      });
    }
    if (!response.ok) {
      throw new ApiCallFailed(apiErrorFromBody(response.status, body));
    }
    const parsed = schema.safeParse(body);
    if (!parsed.success) {
      // Schema mismatch is a contract violation. Surface as internal_error
      // with the Zod error message attached for debugging.
      throw new ApiCallFailed({
        code: "internal_error",
        message: `Response schema mismatch: ${parsed.error.message}`,
      });
    }
    return parsed.data;
  }
}

/** Singleton instance for app-wide use. */
export const apiClient = new ApiClient();
