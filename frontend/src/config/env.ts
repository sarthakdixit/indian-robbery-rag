import { z } from "zod";

// Vite exposes import.meta.env vars prefixed with VITE_. We validate
// at startup so misconfiguration fails fast with a clear message
// rather than mysteriously breaking at runtime.
const EnvSchema = z.object({
  VITE_API_BASE_URL: z.string().url().default("http://localhost:8000"),
  VITE_TURNSTILE_SITE_KEY: z.string().min(1).default("1x00000000000000000000AA"),
  VITE_ENVIRONMENT: z.enum(["local", "cloud"]).default("local"),
});

// import.meta.env's auto-generated index signature is `[key: string]: any`,
// which trips no-unsafe-assignment when we read individual keys. Funnel
// the whole object through Zod instead — Zod ignores unrecognized keys
// and validates the ones we care about.
const rawEnv: Record<string, unknown> = import.meta.env;

/**
 * The validated, typed environment. Throws at module load if any var
 * fails validation (intentional — we want a hard fail at startup, not
 * a confusing runtime error later).
 */
export const env = EnvSchema.parse(rawEnv);

export type Env = z.infer<typeof EnvSchema>;
