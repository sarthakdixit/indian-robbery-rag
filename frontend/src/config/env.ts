import { z } from "zod";

// Vite exposes import.meta.env vars prefixed with VITE_. We validate
// at startup so misconfiguration fails fast with a clear message
// rather than mysteriously breaking at runtime.
const EnvSchema = z.object({
  VITE_API_BASE_URL: z.string().url().default("http://localhost:8000"),
  VITE_TURNSTILE_SITE_KEY: z.string().min(1).default("1x00000000000000000000AA"),
  VITE_ENVIRONMENT: z.enum(["local", "cloud"]).default("local"),
});

/**
 * The validated, typed environment. Throws at module load if any var
 * fails validation (intentional — we want a hard fail at startup, not
 * a confusing runtime error later).
 */
export const env = EnvSchema.parse({
  VITE_API_BASE_URL: import.meta.env.VITE_API_BASE_URL,
  VITE_TURNSTILE_SITE_KEY: import.meta.env.VITE_TURNSTILE_SITE_KEY,
  VITE_ENVIRONMENT: import.meta.env.VITE_ENVIRONMENT,
});

export type Env = z.infer<typeof EnvSchema>;
