import { z } from "zod";
import { CitationSchema } from "./citation";

// Request schema — used by both the form (via Zod resolver) and the
// API client. Single source of truth.
export const QueryRequestSchema = z.object({
  question: z.string().min(3, "Question must be at least 3 characters").max(1000),
  turnstile_token: z.string().min(1, "Turnstile verification required"),
});
export type QueryRequest = z.infer<typeof QueryRequestSchema>;

// Success response from POST /api/query. The backend's PipelineSuccess
// model excludes `prompt_tokens` and `output_tokens` from the HTTP
// response (they're internal), so we don't list them here.
export const QuerySuccessSchema = z.object({
  answer: z.string(),
  citations: z.array(CitationSchema),
  request_id: z.string(),
  cache_hit: z.boolean(),
  latency_ms: z.number(),
});
export type QuerySuccess = z.infer<typeof QuerySuccessSchema>;

// OOS response — same endpoint, same 200, different shape.
export const QueryOutOfScopeSchema = z.object({
  error_code: z.literal("out_of_scope"),
  answer: z.string(),
  citations: z.array(CitationSchema).default([]),
  request_id: z.string(),
  cache_hit: z.boolean(),
  latency_ms: z.number(),
  suggestions: z.array(z.string()).default([]),
});
export type QueryOutOfScope = z.infer<typeof QueryOutOfScopeSchema>;

// Either shape can come back from a 200. The discriminator is the
// presence of `error_code`. The API client narrows this for the
// caller — components consume QuerySuccess or QueryOutOfScope
// directly, never the union.
export const QueryResponseSchema = z.union([QueryOutOfScopeSchema, QuerySuccessSchema]);
export type QueryResponse = z.infer<typeof QueryResponseSchema>;

/** Type-narrowing helper. Use this to branch on the response shape. */
export function isOutOfScope(response: QueryResponse): response is QueryOutOfScope {
  return "error_code" in response && response.error_code === "out_of_scope";
}
