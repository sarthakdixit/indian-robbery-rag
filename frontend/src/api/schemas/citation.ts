import { z } from "zod";

/**
 * Citation card — matches the backend's CitationCard model
 * (backend/app/rag/citations.py). Both source URL fields are nullable:
 * `source_url` is the human-readable web page (Indian Kanoon HTML for
 * judgments, indiacode.nic.in PDF link for acts); `pdf_url` is the
 * authoritative archival PDF (judgments only).
 */
export const CitationSchema = z.object({
  index: z.number().int().positive(),
  source_type: z.enum(["act", "case"]),
  citation: z.string(),
  excerpt: z.string(),
  source_url: z.string().url().nullable(),
  pdf_url: z.string().url().nullable(),
  court: z.string().nullable(),
  year: z.number().int().nullable(),
  metadata: z.record(z.string(), z.unknown()).default({}),
});

export type Citation = z.infer<typeof CitationSchema>;
