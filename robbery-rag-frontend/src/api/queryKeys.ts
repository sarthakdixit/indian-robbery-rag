/**
 * Centralized TanStack Query keys. One source of truth for cache
 * invalidation. Keys are arrays starting with a string discriminator,
 * then narrowing parameters.
 */
export const queryKeys = {
  health: () => ["health"] as const,
  admin: {
    summary: (days?: number) => ["admin", "summary", days] as const,
    topQuestions: (limit: number) => ["admin", "top-questions", limit] as const,
    recentQueries: (limit: number, offset: number) =>
      ["admin", "recent-queries", limit, offset] as const,
  },
} as const;
