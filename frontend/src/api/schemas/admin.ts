import { z } from "zod";

export const DailyStatsSchema = z.object({
  date: z.string(),
  total: z.number().int().nonnegative(),
  successes: z.number().int().nonnegative(),
  rejections: z.number().int().nonnegative(),
  cache_hits: z.number().int().nonnegative(),
  avg_latency_ms: z.number().nullable(),
  estimated_cost_usd: z.number().nonnegative(),
});
export type DailyStats = z.infer<typeof DailyStatsSchema>;

export const SummaryResponseSchema = z.object({
  window_start: z.string(),
  window_end: z.string(),
  total_queries: z.number().int().nonnegative(),
  total_successes: z.number().int().nonnegative(),
  total_rejections: z.number().int().nonnegative(),
  total_cache_hits: z.number().int().nonnegative(),
  rejection_rate: z.number().min(0).max(1),
  cache_hit_rate: z.number().min(0).max(1),
  p50_latency_ms: z.number().nullable(),
  p95_latency_ms: z.number().nullable(),
  total_estimated_cost_usd: z.number().nonnegative(),
  daily: z.array(DailyStatsSchema),
});
export type SummaryResponse = z.infer<typeof SummaryResponseSchema>;

export const TopQuestionEntrySchema = z.object({
  question: z.string(),
  count: z.number().int().positive(),
});
export type TopQuestionEntry = z.infer<typeof TopQuestionEntrySchema>;

export const TopQuestionsResponseSchema = z.object({
  window_start: z.string(),
  window_end: z.string(),
  items: z.array(TopQuestionEntrySchema),
});
export type TopQuestionsResponse = z.infer<typeof TopQuestionsResponseSchema>;

export const RecentQueryEntrySchema = z.object({
  request_id: z.string(),
  timestamp_utc: z.string(),
  hashed_ip_short: z.string(),
  question: z.string(),
  rejected: z.boolean(),
  cache_hit: z.boolean(),
  latency_ms: z.number(),
  citation_count: z.number().int().nonnegative().default(0),
  estimated_cost_usd: z.number().nonnegative().default(0),
});
export type RecentQueryEntry = z.infer<typeof RecentQueryEntrySchema>;

export const RecentQueriesResponseSchema = z.object({
  items: z.array(RecentQueryEntrySchema),
  total: z.number().int().nonnegative(),
  limit: z.number().int().positive(),
  offset: z.number().int().nonnegative(),
});
export type RecentQueriesResponse = z.infer<typeof RecentQueriesResponseSchema>;
