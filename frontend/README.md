# frontend/

The React + TypeScript single-page application that serves as the user interface.

## Purpose

This is the public face of the project. Users land here, click an example question or type their own, see an answer with footnote-style citations, and (in good cases) click through to the authoritative PDF on indiacode.nic.in or the case page on Indian Kanoon.

It also hosts the password-protected `/admin` dashboard for analytics — queries per day, latency, top questions, estimated cost.

## Delivery Model

Unlike the rest of the project (which is built in 4-file chunks), the frontend ships as a **single ZIP file** delivered in Batch 6.

Why: React projects have many small interdependent files — components, hooks, stores, schemas, route configs — where artificial 4-file boundaries would fragment the structure and make the codebase harder to review. The ZIP contains a complete Vite project ready to `pnpm install && pnpm dev`.

See [`../design.md` §11.2](../design.md#112-frontend-exception) for the rationale.

## Layout (anticipated after Batch 6 lands)

```
frontend/
├── src/
│   ├── main.tsx              Entry point
│   ├── App.tsx               Router + providers + error boundary
│   ├── components/
│   │   ├── ui/               shadcn/ui components (copied source)
│   │   ├── layout/           Header, Footer, Banner
│   │   ├── query/            QueryBox, AnswerDisplay, CitationCard
│   │   ├── states/           ColdStartLoader, RateLimitCountdown, ScopeRejectionPanel, ...
│   │   ├── disclaimer/       DisclaimerModal, DisclaimerBanner
│   │   └── admin/            AdminDashboard, charts, tables
│   ├── pages/                HomePage, TermsPage, AdminPage, NotFoundPage
│   ├── hooks/                useSubmitQuery, useLoadingStage, useTurnstileToken
│   ├── stores/               Zustand client-state stores
│   ├── api/                  Typed API client, Zod schemas, query keys
│   ├── config/               Validated env.ts
│   ├── lib/                  cn() helper, formatters
│   └── styles/               Tailwind directives + CSS variables
├── public/
├── tests/
├── package.json
├── pnpm-lock.yaml
├── tsconfig.json
├── vite.config.ts
├── tailwind.config.ts
└── .env.example
```

## Status

Empty scaffolding. The full project arrives as a ZIP in **Batch 6**.

## Coding Conventions

Read [`../AGENT-frontend.md`](../AGENT-frontend.md) before writing any frontend code. Key rules in short form:

- `tsc --strict` clean, `noUncheckedIndexedAccess: true`
- TanStack Query owns server state; Zustand owns client state. Never mix.
- Tailwind only, no inline styles, no CSS modules
- Accessibility is correctness (keyboard nav, ARIA where needed, WCAG AA contrast)
- API responses validated with Zod at the boundary — no `as` casts

## Local Development

_Setup commands will land with Batch 6._

The intent:

```bash
cd frontend
pnpm install
cp .env.example .env
pnpm dev
```

Connects to a local backend running at `http://localhost:8000` by default.
