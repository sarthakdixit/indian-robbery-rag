# Frontend — Robbery Law RAG Assistant

Vite + React 18 + TypeScript (strict) + Tailwind CSS. Connects to the
backend at `http://localhost:8000` (configurable via `VITE_API_BASE_URL`).

## Quick start

```bash
# 1. Install deps. pnpm is recommended (per AGENT-frontend.md §2.2);
#    npm works too. This regenerates the lockfile on first run.
pnpm install

# 2. Copy env template and adjust if needed
cp .env.example .env.local

# 3. Start dev server
pnpm dev
# Open http://localhost:5173
```

The Vite dev server proxies `/api/*` to `http://localhost:8000` so you
don't see CORS errors. Start the backend first (`make dev` from the
backend dir).

## Scripts

| Command             | Purpose                                     |
| ------------------- | ------------------------------------------- |
| `pnpm dev`          | Vite dev server with HMR on :5173           |
| `pnpm build`        | Type-check + produce `dist/` for SWA deploy |
| `pnpm preview`      | Serve the built `dist/` locally             |
| `pnpm lint`         | ESLint (strict + react-hooks + jsx-a11y)    |
| `pnpm format`       | Prettier write                              |
| `pnpm format:check` | Prettier check (CI gate)                    |
| `pnpm typecheck`    | `tsc --noEmit`                              |
| `pnpm test`         | Vitest run                                  |

Pre-commit gate: `pnpm typecheck && pnpm lint && pnpm format:check && pnpm test`.

## Stack

| Layer          | Choice                | Why                                |
| -------------- | --------------------- | ---------------------------------- |
| Server state   | TanStack Query        | Cache + retries handled            |
| Client state   | Zustand               | Tiny, no providers                 |
| Forms          | React Hook Form + Zod | Schema-driven validation           |
| Routing        | React Router v6       | data-router pattern                |
| Styling        | Tailwind + shadcn/ui  | Unbranded, copyable components     |
| Bot protection | Cloudflare Turnstile  | Free, invisible CAPTCHA            |
| HTTP           | `fetch` (native)      | No axios, see AGENT-frontend.md §2 |

## Layout

```
src/
├── api/              # ApiClient + Zod schemas + query keys
├── components/
│   ├── ui/           # shadcn/ui primitives (button, dialog, etc.)
│   ├── layout/       # Header, Footer
│   ├── query/        # Query box, answer, citations
│   ├── states/       # Loading/error/rate-limit/OOS panels
│   ├── disclaimer/   # First-visit modal + per-answer banner
│   └── admin/        # Dashboard
├── config/env.ts     # Zod-validated env
├── hooks/            # useSubmitQuery, useTurnstileToken, etc.
├── lib/utils.ts      # cn() helper
├── pages/            # HomePage, AdminPage, TermsPage, NotFoundPage
├── stores/           # Zustand: disclaimer, query input
└── styles/globals.css
```

## Notes on conventions

The full convention guide is `AGENT-frontend.md` at the repo root. Key
rules enforced here:

- **TypeScript strict** (`noUncheckedIndexedAccess`, `exactOptionalPropertyTypes`)
- **No `any`** — narrow `unknown` with Zod or type guards
- **Server state ↔ TanStack Query; client state ↔ Zustand. Never mix.**
- **Components are dumb by default** — logic in hooks
- **Tailwind only** — no inline `style={{}}`, no CSS files except `globals.css`
- **Discriminated unions** for multi-state values

## Known gaps

- `pnpm-lock.yaml` is not committed (would need machine-generation).
  Run `pnpm install` once after extraction to produce it. AGENT-frontend.md
  §2.2 says it should be committed; deferred for now.
- The admin dashboard is functional but not visually polished. A v2
  would replace the plain tables with a chart library.
- The pre-populated demo cache (FR-7) is wired client-side via demo
  example buttons; backend pre-population is a Batch 8 task.
