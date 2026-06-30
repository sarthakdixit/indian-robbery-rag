import { z } from "zod";

// Backend error envelope: { error_code, message, request_id? }
// Mirrors backend/app/errors.py
const BackendErrorBodySchema = z.object({
  error_code: z.string(),
  message: z.string(),
  request_id: z.string().optional(),
  // OOS responses include this; admin error responses don't.
  suggestions: z.array(z.string()).optional(),
  // Rate limit responses might include this — keep room for it.
  resetAt: z.number().optional(),
});
type BackendErrorBody = z.infer<typeof BackendErrorBodySchema>;

/**
 * Frontend-side typed error. Discriminated union by `code`, matching
 * the backend's `error_code` field. Components consume this via
 * exhaustive `switch (error.code) { ... }` patterns — TypeScript
 * enforces handling every case.
 */
export type ApiError =
  | { code: "rate_limit_exceeded"; message: string; resetAt?: number }
  | { code: "out_of_scope"; message: string; suggestions: string[] }
  | { code: "turnstile_failed"; message: string }
  | { code: "demo_at_capacity"; message: string }
  | { code: "llm_unavailable"; message: string }
  | { code: "admin_auth_failed"; message: string }
  | { code: "invalid_query"; message: string }
  | { code: "citation_verification_failed"; message: string }
  | { code: "internal_error"; message: string }
  | { code: "network_error"; message: string };

/**
 * Build a typed ApiError from a non-OK fetch response body. Falls
 * back to "internal_error" if the body doesn't match the expected
 * envelope shape — defensive against future backend changes.
 */
export function apiErrorFromBody(_status: number, raw: unknown): ApiError {
  const parsed = BackendErrorBodySchema.safeParse(raw);
  if (!parsed.success) {
    return { code: "internal_error", message: "Unrecognized error response" };
  }
  const body: BackendErrorBody = parsed.data;
  // Each branch narrows the union appropriately.
  switch (body.error_code) {
    case "rate_limit_exceeded":
      return { code: "rate_limit_exceeded", message: body.message, ...(body.resetAt !== undefined && { resetAt: body.resetAt }) };
    case "out_of_scope":
      return {
        code: "out_of_scope",
        message: body.message,
        suggestions: body.suggestions ?? [],
      };
    case "turnstile_failed":
    case "demo_at_capacity":
    case "llm_unavailable":
    case "admin_auth_failed":
    case "invalid_query":
    case "citation_verification_failed":
    case "internal_error":
      return { code: body.error_code, message: body.message };
    default:
      return { code: "internal_error", message: body.message };
  }
}

/** Build a network-error ApiError (no response received). */
export function networkError(detail: string): ApiError {
  return { code: "network_error", message: `Network error: ${detail}` };
}
