# AGENT.md (Frontend) — React + TypeScript Coding Conventions

> **Audience:** AI coding agents and human contributors writing frontend code for this repository.
> **Status:** Authoritative. When this file conflicts with code, the code is wrong.
> **Scope:** Applies to everything under `frontend/`. The backend has its own `AGENT.md` with different conventions.
> **Delivery:** The frontend ships as a single ZIP file, not in 4-file chunks (see `design.md`).

---

## Table of Contents

1. [Core Principles](#1-core-principles)
2. [Stack & Tooling](#2-stack--tooling)
3. [TypeScript Conventions](#3-typescript-conventions)
4. [Component Conventions](#4-component-conventions)
5. [Naming](#5-naming)
6. [Comments & Documentation](#6-comments--documentation)
7. [State Management](#7-state-management)
8. [API Layer & Server State](#8-api-layer--server-state)
9. [Styling](#9-styling)
10. [Accessibility](#10-accessibility)
11. [Forms & Validation](#11-forms--validation)
12. [Error Handling & Boundaries](#12-error-handling--boundaries)
13. [Routing](#13-routing)
14. [Environment & Configuration](#14-environment--configuration)
15. [Testing](#15-testing)
16. [Performance](#16-performance)
17. [File Organization](#17-file-organization)
18. [Linting, Formatting & Type Checking](#18-linting-formatting--type-checking)
19. [Common Anti-Patterns](#19-common-anti-patterns)
20. [Library-Specific Notes](#20-library-specific-notes)

---

## 1. Core Principles

These five override any rule below if there is a conflict.

1. **Strict types, always.** `tsc --strict` clean. No `any` without a justified `// eslint-disable-next-line` and a "why" comment.
2. **Server state belongs to TanStack Query. Client state belongs to Zustand.** Never mix.
3. **Components are dumb by default.** Logic lives in hooks, stores, or API clients — not inside JSX.
4. **Names over comments.** If a prop, component, or hook needs a comment to be understandable, rename it.
5. **Accessibility is not optional.** Keyboard navigation, semantic HTML, ARIA where needed, color contrast — these are correctness, not polish.

---

## 2. Stack & Tooling

| Layer | Choice |
|---|---|
| Build tool | Vite |
| Language | TypeScript (strict) |
| UI framework | React 18+ with function components |
| Styling | Tailwind CSS |
| Component primitives | shadcn/ui (copied into `src/components/ui/`) |
| Icons | `lucide-react` |
| Client state | Zustand |
| Server state | TanStack Query (React Query v5) |
| Routing | React Router v6+ |
| Forms | React Hook Form + Zod resolvers |
| Schema validation | Zod (shared schemas where possible) |
| HTTP client | `fetch` wrapped in a typed client (no axios) |
| Testing | Vitest + React Testing Library + `@testing-library/user-event` |
| E2E (optional) | Playwright, happy-path smoke only |
| Linting | ESLint with `typescript-eslint`, `eslint-plugin-react-hooks`, `eslint-plugin-jsx-a11y` |
| Formatting | Prettier (delegated; no style debates in PRs) |
| Bot protection | `@marsidev/react-turnstile` for Cloudflare Turnstile |

### 2.1 Node Version

Node 20 LTS. Pinned in `.nvmrc` and `engines` in `package.json`.

### 2.2 Package Manager

`pnpm`. Faster, deterministic, and produces smaller `node_modules`. Lockfile (`pnpm-lock.yaml`) committed.

---

## 3. TypeScript Conventions

### 3.1 `tsconfig.json` Required Settings

```jsonc
{
  "compilerOptions": {
    "strict": true,
    "noUncheckedIndexedAccess": true,
    "noImplicitOverride": true,
    "noFallthroughCasesInSwitch": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "exactOptionalPropertyTypes": true,
    "verbatimModuleSyntax": true,
    "isolatedModules": true,
    "target": "ES2022",
    "module": "ESNext",
    "moduleResolution": "bundler",
    "jsx": "react-jsx"
  }
}
```

`noUncheckedIndexedAccess` is non-negotiable. It catches the `arr[0].foo` class of runtime crashes at compile time.

### 3.2 Type Inference vs Explicit Types

- **Component props:** always explicit `type Props = {...}`.
- **Hook return types:** explicit when the hook is exported, inferred when local.
- **Local variables:** inferred unless inference is wrong or misleading.
- **Function parameters:** always explicit.
- **Function return types:** explicit on exported functions, inferred on locals.

```tsx
// Good — explicit on the boundary, inferred locally
type CitationCardProps = {
  citation: Citation;
  index: number;
  onExpand: (index: number) => void;
};

export function CitationCard({ citation, index, onExpand }: CitationCardProps): JSX.Element {
  const isExpanded = useCitationExpansion(index);
  return <div>...</div>;
}
```

### 3.3 No `any`, No `unknown` Without Narrowing

- `any` is forbidden. If a third-party library returns `any`, narrow it immediately with Zod or a type guard.
- `unknown` is allowed but must be narrowed before use.
- `as` assertions need a "why" comment unless the cast is a Zod-validated parse result.

```tsx
// Rejected
const data = response.json() as ApiResponse;

// Correct
const data = ApiResponseSchema.parse(await response.json());
```

### 3.4 Discriminated Unions for State

When a value can be in one of several distinct states, model it as a discriminated union, never as a bag of optional fields.

```tsx
// Rejected — optional fields hide invariants
type QueryState = {
  isLoading?: boolean;
  data?: QueryResponse;
  error?: ApiError;
};

// Correct — exhaustive states with compile-time guarantees
type QueryState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "success"; data: QueryResponse }
  | { status: "error"; error: ApiError }
  | { status: "rate_limited"; resetAt: number }
  | { status: "out_of_scope"; suggestions: string[] };
```

### 3.5 Branded Types for Identifiers

Distinguish identifier strings at compile time:

```tsx
type RequestId = string & { readonly __brand: "RequestId" };
type CitationIndex = number & { readonly __brand: "CitationIndex" };
```

Use these for anything that could be accidentally confused (request IDs, hashed IPs, citation indices).

### 3.6 Type vs Interface

Use `type` for everything. Only use `interface` when you specifically need declaration merging (rare). Consistency beats theology.

---

## 4. Component Conventions

### 4.1 Function Components Only

No class components. No `React.FC`. Use plain function declarations with explicit return types.

```tsx
// Rejected
const QueryBox: React.FC<QueryBoxProps> = ({ onSubmit }) => { ... };

// Correct
export function QueryBox({ onSubmit }: QueryBoxProps): JSX.Element { ... }
```

`React.FC` adds implicit `children` and complicates generics. Plain functions are clearer.

### 4.2 One Component Per File

A `.tsx` file exports exactly one component (plus its prop type and any colocated subcomponents that are not reused elsewhere). File name matches the component name in `PascalCase.tsx`.

### 4.3 Component Size

Soft cap: 150 lines. Hard cap: 250 lines. Components above the soft cap should be split into subcomponents or have logic extracted to hooks.

### 4.4 Props Conventions

- Props are destructured in the parameter list.
- No more than 7 props on a single component. Beyond that, group into objects or split the component.
- Boolean props are unprefixed when they describe state (`disabled`, `loading`) and prefixed `is*`/`has*` when they describe identity (`isActive`, `hasError`).
- Event handlers are prefixed `on*` (`onSubmit`, `onCitationExpand`).
- Render props are prefixed `render*` (rare; prefer composition).

### 4.5 No Inline Functions in Hot Paths

Lists rendering many items should not create new function instances per render unless memoized. For low-volume UI (a header, a modal), inline arrow functions are fine.

```tsx
// Rejected for a 1000-item list
{items.map(item => (
  <Row key={item.id} onClick={() => handleClick(item.id)} />
))}

// Correct
const handleRowClick = useCallback((id: string) => { ... }, [...]);
{items.map(item => (
  <Row key={item.id} id={item.id} onClick={handleRowClick} />
))}
```

For this project's actual scale (citations list, recent queries table), inline arrows are acceptable.

### 4.6 JSX Conventions

- Self-closing tags for elements with no children: `<input />` not `<input></input>`.
- Boolean props shortened: `<Button disabled>` not `<Button disabled={true}>`.
- Conditional rendering uses `&&` for "render or nothing" and ternaries for "either/or". Never nested ternaries.

```tsx
// Rejected
{isLoading ? <Spinner /> : isError ? <Error /> : <Result data={data} />}

// Correct — discriminated union renders cleanly
{queryState.status === "loading" && <Spinner />}
{queryState.status === "error" && <ErrorPanel error={queryState.error} />}
{queryState.status === "success" && <Result data={queryState.data} />}
```

---

## 5. Naming

### 5.1 Files & Folders

- Components: `PascalCase.tsx` — `CitationCard.tsx`, `DisclaimerModal.tsx`
- Hooks: `useCamelCase.ts` — `useQuerySubmission.ts`, `useDisclaimerAccepted.ts`
- Stores: `useCamelCaseStore.ts` — `useDisclaimerStore.ts`
- Utilities: `camelCase.ts` — `formatLatency.ts`, `hashQueryForCache.ts`
- Types: `camelCase.types.ts` or colocated with the component
- Tests: mirror the source filename with `.test.tsx` or `.test.ts`

Folders: `kebab-case` — `citation-card/`, `admin-dashboard/`. Never `PascalCase` folders.

### 5.2 Component Names

Component names describe what the component IS, not what it does.

```tsx
// Good
CitationCard
DisclaimerModal
RateLimitCountdown
ScopeRejectionPanel
ColdStartLoadingIndicator
QueryInputBox
AnswerDisplay

// Bad
Card                   // Too generic
ShowDisclaimer         // Verb — sounds like a function
Modal                  // Which modal?
Stuff                  // Just no
```

### 5.3 Hook Names

Hooks always start with `use`. The name describes what the hook returns or manages.

```tsx
// Good
useQuerySubmission()        // returns submit function + state
useDisclaimerAccepted()     // returns boolean + setter
useCitationExpansion()      // manages which citations are open
useTurnstileToken()         // returns token, refresh

// Bad
getQuerySubmission()        // missing use prefix
useStuff()                  // unclear what it does
useDisclaimer()             // returns what?
```

### 5.4 Boolean Variables

Same rules as backend: `is*`, `has*`, `should*`, `can*`.

```tsx
const isDisclaimerAccepted = useDisclaimerStore(s => s.isAccepted);
const hasReachedRateLimit = queryState.status === "rate_limited";
const shouldShowColdStartLoader = elapsedMs > 3000;
const canSubmitQuery = !isLoading && question.length > 0 && hasValidTurnstileToken;
```

### 5.5 Event Handlers

Two patterns, picked based on where the handler is defined:

- **Inside the component:** `handle*` — `handleSubmit`, `handleCitationClick`
- **As a prop received from parent:** `on*` — `onSubmit`, `onCitationExpand`

```tsx
type Props = { onSubmit: (q: string) => void };

export function QueryBox({ onSubmit }: Props): JSX.Element {
  const handleClick = () => onSubmit(question);
  return <button onClick={handleClick}>Ask</button>;
}
```

---

## 6. Comments & Documentation

Same pragmatic rules as the backend.

### 6.1 No "What" Comments

```tsx
// Rejected — code is already self-explanatory
// Submit the query
handleSubmit();

// Rejected — restates the obvious
// Set loading to true
setIsLoading(true);
```

### 6.2 "Why" Comments Allowed

When the *reason* is non-obvious and cannot be encoded in names, a comment is justified.

```tsx
// Turnstile token expires after ~5 minutes; refresh proactively at 4min to avoid
// rejection on the next user submit. See https://developers.cloudflare.com/turnstile/...
const TURNSTILE_REFRESH_MS = 240_000;

// We delay the cold-start message by 3s so warm-cache hits never show it.
// Eval data shows median warm response is 1.4s.
const COLD_START_MESSAGE_DELAY_MS = 3000;
```

### 6.3 JSDoc

Allowed and encouraged on **exported public APIs** when types alone are not enough:

```tsx
/** Returns a stable cache key that ignores whitespace and casing. */
export function normalizeQueryForCacheKey(query: string): string { ... }
```

Skip JSDoc on:
- Internal helpers
- Components whose props are self-evident from the type
- Stores whose actions have descriptive names

### 6.4 TODO / FIXME

Must reference an issue: `// TODO(#42): description`. Bare `// TODO` is rejected by ESLint.

---

## 7. State Management

The single most important rule: **server state belongs to TanStack Query. Client state belongs to Zustand. Never mix.**

### 7.1 Server State (TanStack Query)

Anything that originates on the backend — query responses, rate limit status returned by the API, admin metrics — is server state. Use `useQuery` and `useMutation`.

```tsx
export function useSubmitQuery() {
  return useMutation({
    mutationFn: (input: SubmitQueryInput) => apiClient.submitQuery(input),
    retry: false,
  });
}
```

Server state is never mirrored into Zustand. If you find yourself doing `useEffect(() => setStore(data), [data])`, you are doing it wrong — read directly from the query.

### 7.2 Client State (Zustand)

UI-only state that has no backend representation: disclaimer-accepted flag, current input text, which citations are expanded, selected admin date range.

```tsx
type DisclaimerStore = {
  isAccepted: boolean;
  accept: () => void;
};

export const useDisclaimerStore = create<DisclaimerStore>()(
  persist(
    (set) => ({
      isAccepted: false,
      accept: () => set({ isAccepted: true }),
    }),
    { name: "disclaimer-storage" }
  )
);
```

### 7.3 Store Slicing

One store per concern. Do not create a single mega-store.

```
src/stores/
  useDisclaimerStore.ts
  useQueryInputStore.ts
  useCitationExpansionStore.ts
  useAdminFilterStore.ts
```

### 7.4 Selector Pattern

Always read with a selector to minimize re-renders. Never destructure the whole store.

```tsx
// Rejected — re-renders on any store change
const { isAccepted, accept } = useDisclaimerStore();

// Correct — re-renders only when isAccepted changes
const isAccepted = useDisclaimerStore(s => s.isAccepted);
const accept = useDisclaimerStore(s => s.accept);
```

### 7.5 Persistence

Use Zustand's `persist` middleware for state that should survive reloads (disclaimer accepted flag). Do NOT persist sensitive data — there is none in this project, but the rule stands.

### 7.6 Local Component State

`useState` is the right answer for state confined to one component (e.g., a controlled input). Don't reach for Zustand when `useState` works.

Decision tree:
- Used in one component → `useState`
- Shared across siblings → lift to common parent, then `useState` or `useReducer`
- Truly global, persists across routes → Zustand
- Comes from the API → TanStack Query

---

## 8. API Layer & Server State

### 8.1 Typed API Client

A single typed client wraps `fetch`. No direct `fetch()` calls in components.

```tsx
// src/api/client.ts
export class ApiClient {
  constructor(private readonly baseUrl: string) {}

  async submitQuery(input: SubmitQueryInput): Promise<QueryResponse> {
    const response = await fetch(`${this.baseUrl}/api/query`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    });
    return this.handleResponse(response, QueryResponseSchema);
  }

  private async handleResponse<T>(response: Response, schema: ZodSchema<T>): Promise<T> {
    const body = await response.json();
    if (!response.ok) {
      throw ApiError.fromResponseBody(response.status, body);
    }
    return schema.parse(body);
  }
}
```

### 8.2 Response Schemas with Zod

Every API response is validated with Zod at the boundary. The Zod schema is the source of truth for response types.

```tsx
export const CitationSchema = z.object({
  index: z.number().int().positive(),
  source_type: z.enum(["act", "case"]),
  citation: z.string(),
  excerpt: z.string(),
  source_url: z.string().url().nullable(),  // Indian Kanoon HTML page (judgments) or indiacode.nic.in (acts)
  pdf_url: z.string().url().nullable(),     // Authoritative PDF archival copy (judgments only)
  court: z.string().nullable(),             // "Supreme Court", "Delhi High Court", etc. — null for acts
  year: z.number().int().nullable(),
  metadata: z.record(z.string(), z.unknown()),
});

export const QueryResponseSchema = z.object({
  answer: z.string(),
  citations: z.array(CitationSchema),
  request_id: z.string(),
  cache_hit: z.boolean(),
  latency_ms: z.number(),
});

export type QueryResponse = z.infer<typeof QueryResponseSchema>;
```

Citation card UI should expose both links when present: a primary "View on Indian Kanoon" link (HTML, easier to read inline) and a secondary "Download official PDF" link (authoritative archival copy). For statutory citations, only `source_url` is populated. Court and year render as small metadata pills below the citation header.

### 8.3 Typed Errors

`ApiError` is a discriminated union matching the backend's `error_code` field.

```tsx
type ApiError =
  | { code: "rate_limit_exceeded"; resetAt: number }
  | { code: "out_of_scope"; suggestions: string[] }
  | { code: "turnstile_failed" }
  | { code: "demo_at_capacity" }
  | { code: "llm_unavailable" }
  | { code: "internal_error"; message: string };
```

Mapping happens once in `ApiClient.handleResponse`. Components consume the typed union — never raw HTTP status codes.

### 8.4 TanStack Query Configuration

```tsx
const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: false, refetchOnWindowFocus: false, staleTime: 60_000 },
    mutations: { retry: false },
  },
});
```

No automatic retries — a failed query is an explicit error the user sees. Retries on a legal Q&A system would burn through rate limits silently.

### 8.5 Query Keys

Query keys are arrays starting with a string discriminator, then narrowing parameters:

```tsx
queryKey: ["admin-metrics", dateRange]
queryKey: ["admin-recent-queries", { limit, offset }]
```

Centralize key construction in a `src/api/queryKeys.ts` module so cache invalidation has one source of truth.

---

## 9. Styling

### 9.1 Tailwind First, Always

All styling uses Tailwind utility classes. No CSS files except `index.css` (Tailwind directives) and any `globals.css` for resets.

```tsx
// Correct
<div className="flex flex-col gap-4 rounded-lg border bg-card p-6">

// Rejected
<div style={{ display: "flex", flexDirection: "column" }}>
<div className={styles.container}>
```

### 9.2 shadcn/ui Components

shadcn/ui components are **copied** into `src/components/ui/` via the CLI. They are part of the codebase, not a dependency.

- Modify them freely to match the design.
- Re-run the CLI only when explicitly adopting a new component or upstream patch.
- Customize through Tailwind classes via `cn()` and component variants.

### 9.3 The `cn()` Helper

Composes Tailwind classes conditionally. Use it for any non-trivial conditional styling.

```tsx
import { cn } from "@/lib/utils";

<button
  className={cn(
    "rounded-md px-4 py-2 font-medium",
    isPrimary ? "bg-primary text-primary-foreground" : "bg-secondary",
    isDisabled && "cursor-not-allowed opacity-50",
  )}
>
```

### 9.4 Design Tokens

Theme colors, spacing, radii defined in `tailwind.config.ts`. shadcn/ui uses CSS variables for theming — colors are HSL triplets in `globals.css`. To change the theme, modify the CSS variables, not the components.

### 9.5 No Inline Styles

Inline `style={{...}}` is forbidden except for one case: dynamic values that cannot be expressed in Tailwind (e.g., a progress bar width computed at runtime).

```tsx
// Acceptable exception
<div className="h-2 rounded-full bg-primary" style={{ width: `${percent}%` }} />
```

### 9.6 Responsive Design

Mobile-first. Use Tailwind breakpoint prefixes (`md:`, `lg:`). The site must be fully usable on a 375px-wide screen because recruiters often click demo links from mobile.

```tsx
<div className="flex flex-col gap-4 md:flex-row md:gap-8">
```

### 9.7 Dark Mode

Required. Use shadcn/ui's `next-themes` integration (or its non-Next equivalent). Test every component in both modes. No `dark:` prefix on hardcoded colors — use the semantic tokens (`bg-background`, `text-foreground`).

---

## 10. Accessibility

Accessibility is correctness, not polish.

### 10.1 Required Behaviors

- **Keyboard navigation:** every interactive element reachable and operable with Tab/Shift-Tab and Enter/Space.
- **Focus visible:** never `outline-none` without a replacement focus ring.
- **Semantic HTML:** `<button>` for buttons, `<a>` for links, `<form>` for forms, headings in order.
- **Labels on inputs:** every form input has an associated `<label>` or `aria-label`.
- **Color contrast:** WCAG AA minimum (4.5:1 for normal text).
- **No information conveyed by color alone:** rate limit error has icon + text, not just red.

### 10.2 Modals

The disclaimer modal must:
- Trap focus inside while open
- Close on Escape
- Restore focus to the trigger on close
- Have `role="dialog"` and `aria-labelledby`

shadcn/ui's `Dialog` handles all of this correctly. Use it; do not roll your own.

### 10.3 Screen Reader Considerations

- Loading states announce themselves: `<div role="status" aria-live="polite">Loading answer...</div>`
- Error states use `role="alert"` for immediate announcement
- Citations indices in the answer text are read meaningfully (use `<sup>` and label appropriately)

### 10.4 ESLint Plugin

`eslint-plugin-jsx-a11y` is enabled with recommended rules. Violations block CI.

---

## 11. Forms & Validation

### 11.1 React Hook Form + Zod

All forms use `react-hook-form` with `@hookform/resolvers/zod`. The Zod schema validates and provides types.

```tsx
const QueryFormSchema = z.object({
  question: z.string().min(3, "Question must be at least 3 characters").max(1000),
});

type QueryFormValues = z.infer<typeof QueryFormSchema>;

export function QueryForm({ onSubmit }: Props): JSX.Element {
  const form = useForm<QueryFormValues>({
    resolver: zodResolver(QueryFormSchema),
    defaultValues: { question: "" },
  });
  ...
}
```

### 11.2 Shared Schemas

Where a Zod schema can be shared between frontend and backend (e.g., the request body shape), define it in `src/api/schemas/` and reference it in both the form and the API client.

### 11.3 Error Display

Errors render inline, not in a banner at the top. Each field's error is colocated with the field. The first error receives focus on submit.

---

## 12. Error Handling & Boundaries

### 12.1 React Error Boundary

A single top-level Error Boundary wraps the app. It catches render errors and shows the generic fallback UI.

```tsx
<ErrorBoundary fallback={<GenericErrorFallback />}>
  <App />
</ErrorBoundary>
```

Use a library (`react-error-boundary`) — do not hand-roll. Error boundaries do NOT catch async errors; those come through TanStack Query as `error` state.

### 12.2 API Errors

Handle by the discriminated `ApiError.code`:

```tsx
const mutation = useSubmitQuery();

if (mutation.error) {
  switch (mutation.error.code) {
    case "rate_limit_exceeded":
      return <RateLimitCountdown resetAt={mutation.error.resetAt} />;
    case "out_of_scope":
      return <ScopeRejectionPanel suggestions={mutation.error.suggestions} />;
    case "demo_at_capacity":
      return <CapacityReachedPanel />;
    case "llm_unavailable":
      return <LlmUnavailablePanel />;
    case "turnstile_failed":
      return <TurnstileFailurePanel onRetry={...} />;
    default:
      return <GenericErrorPanel />;
  }
}
```

The switch is exhaustive — TypeScript will fail if a new error code is added without a case (use a `never` check in the default).

### 12.3 Cold Start UX

The query submission shows three loading stages, determined by elapsed time:

1. `0–3000ms` — Subtle spinner only
2. `3000–10000ms` — "Warming up the legal research engine, takes ~10 seconds on first visit"
3. `10000ms+` — "Still warming up... almost there"

Implement with a custom hook that emits the current stage:

```tsx
const loadingStage = useLoadingStage(mutation.isPending);
```

---

## 13. Routing

### 13.1 Routes

```
/             Home (query + answer)
/terms        Terms of Use
/admin        Admin dashboard (password-protected)
*             404 fallback
```

### 13.2 React Router Conventions

- Use the data router pattern (`createBrowserRouter`).
- Lazy-load `/admin` to keep the main bundle small.
- 404 fallback is a real route, not an undefined behavior.

### 13.3 Admin Route Protection

The `/admin` route uses a simple password check stored client-side (NOT a real auth boundary — the actual protection is the backend rejecting unauthenticated admin API calls). The password is sent as an HTTP header on admin API requests.

This intentionally trivial protection is acceptable for a portfolio demo and documented in the README. The real protection is server-side.

---

## 14. Environment & Configuration

### 14.1 Vite Env Vars

All env vars start with `VITE_` (Vite requires this). Defined in `.env`, `.env.local`, etc. The example file `.env.example` is committed.

```
VITE_API_BASE_URL=http://localhost:8000
VITE_TURNSTILE_SITE_KEY=1x00000000000000000000AA
VITE_ENVIRONMENT=local
```

### 14.2 Typed Env Access

Never use `import.meta.env.VITE_FOO` directly in components. Centralize in `src/config/env.ts`:

```tsx
import { z } from "zod";

const EnvSchema = z.object({
  VITE_API_BASE_URL: z.string().url(),
  VITE_TURNSTILE_SITE_KEY: z.string().min(1),
  VITE_ENVIRONMENT: z.enum(["local", "cloud"]),
});

export const env = EnvSchema.parse(import.meta.env);
```

Validation happens once at startup. Misconfiguration fails fast with a clear error.

### 14.3 Local vs Cloud

Local development uses the Turnstile test site key (`1x00000000000000000000AA`) which always returns valid. Cloud uses the real site key from Cloudflare.

This mirrors the backend's "local adapter always validates" pattern.

---

## 15. Testing

### 15.1 Framework

Vitest + React Testing Library + `@testing-library/user-event` v14.

### 15.2 What to Test

- **Pure functions:** unit tests, no mocks needed.
- **Hooks:** with `renderHook` from RTL.
- **Components:** behavior, not implementation. Click buttons, fill inputs, assert visible output.
- **Stores:** call actions, assert state.
- **API client:** with MSW (Mock Service Worker) to mock HTTP.

### 15.3 What NOT to Test

- **Snapshot tests:** brittle and produce noisy diffs. Test specific assertions.
- **Implementation details:** don't test "useState was called". Test user-visible behavior.
- **Third-party components:** trust shadcn/ui works. Test your usage of it.

### 15.4 Test Naming

Test file mirrors source file: `CitationCard.tsx` → `CitationCard.test.tsx`. Test names describe behavior:

```tsx
describe("CitationCard", () => {
  it("renders the citation text and metadata", () => { ... });
  it("expands when the user clicks the card", async () => { ... });
  it("collapses when the user clicks again", async () => { ... });
});
```

### 15.5 RTL Queries

Prefer queries in this order:
1. `getByRole` — accessible, mirrors how users find elements
2. `getByLabelText` — for form inputs
3. `getByText` — for content
4. `getByTestId` — last resort

`getByTestId` requires adding `data-testid` to the component, which is allowed but should be rare.

### 15.6 User Events, Not Fire Events

```tsx
// Rejected
fireEvent.click(button);

// Correct
const user = userEvent.setup();
await user.click(button);
```

`userEvent` simulates real user behavior (focus, hover, keyboard).

### 15.7 Coverage

Target 70% on `src/`. Not a CI gate. Focus on critical paths: query submission flow, error state handling, disclaimer flow.

---

## 16. Performance

### 16.1 Bundle Size

Initial JS bundle target: under 200KB gzipped. Audit with `pnpm build && pnpm dlx vite-bundle-visualizer`.

Strategies:
- Lazy-load `/admin` route (it's not on the critical path for most users)
- Tree-shakeable imports: `import { Button } from "@/components/ui/button"` not from a barrel
- Avoid `lodash` — use native methods or `lodash-es` with specific imports

### 16.2 Re-render Discipline

- Use `React.memo` only after measuring, not preemptively
- Use Zustand selectors to scope subscriptions narrowly
- Co-locate state with where it's used (lift state up only when needed by siblings)

### 16.3 Image Optimization

- Use SVG for icons (lucide-react handles this)
- Use WebP for raster images
- All images have `width` and `height` attributes to prevent CLS

### 16.4 No Unnecessary Animations

Animations are subtle and short (<300ms). Respect `prefers-reduced-motion`:

```tsx
<div className="transition-opacity duration-200 motion-reduce:transition-none">
```

---

## 17. File Organization

### 17.1 Layout

```
frontend/
  src/
    main.tsx                    Entry point: mounts <App /> with providers
    App.tsx                     Router + ErrorBoundary + providers
    components/
      ui/                       shadcn/ui components (copied source)
        button.tsx
        dialog.tsx
        ...
      layout/
        Header.tsx
        Footer.tsx
        DisclaimerBanner.tsx
      query/
        QueryBox.tsx
        AnswerDisplay.tsx
        CitationCard.tsx
        CitationList.tsx
        DemoExampleButtons.tsx
      states/
        ColdStartLoader.tsx
        RateLimitCountdown.tsx
        ScopeRejectionPanel.tsx
        CapacityReachedPanel.tsx
        LlmUnavailablePanel.tsx
        GenericErrorFallback.tsx
      disclaimer/
        DisclaimerModal.tsx
        DisclaimerBanner.tsx
      admin/
        AdminDashboard.tsx
        MetricsCards.tsx
        QueriesChart.tsx
        TopQuestionsTable.tsx
        RecentQueriesTable.tsx
    pages/
      HomePage.tsx
      TermsPage.tsx
      AdminPage.tsx
      NotFoundPage.tsx
    hooks/
      useSubmitQuery.ts
      useLoadingStage.ts
      useTurnstileToken.ts
      useCitationExpansion.ts
    stores/
      useDisclaimerStore.ts
      useQueryInputStore.ts
    api/
      client.ts
      schemas/
        query.ts
        citation.ts
        admin.ts
        error.ts
      queryKeys.ts
      errors.ts
    config/
      env.ts
      constants.ts
    lib/
      utils.ts                  cn() helper
      formatLatency.ts
      formatCost.ts
    styles/
      globals.css               Tailwind directives + CSS variables
  public/
    favicon.svg
    robots.txt
  tests/
    setup.ts                    Vitest setup, MSW server
  index.html
  package.json
  pnpm-lock.yaml
  tsconfig.json
  tsconfig.node.json
  vite.config.ts
  vitest.config.ts
  tailwind.config.ts
  postcss.config.js
  .eslintrc.cjs
  .prettierrc
  .env.example
  components.json               shadcn/ui config
```

### 17.2 Path Aliases

```jsonc
// tsconfig.json
"paths": {
  "@/*": ["./src/*"]
}
```

Always use `@/` imports for `src/` paths. Never `../../../`.

```tsx
// Rejected
import { Button } from "../../../components/ui/button";

// Correct
import { Button } from "@/components/ui/button";
```

### 17.3 No Barrel Files

`index.ts` files that re-export everything from a folder are forbidden. They defeat tree-shaking and create circular import risk. Always import from the source file directly.

---

## 18. Linting, Formatting & Type Checking

### 18.1 Tools

- **ESLint** — with `typescript-eslint`, `react-hooks`, `jsx-a11y`, `react-refresh`
- **Prettier** — formatting only, no overlap with ESLint
- **tsc** — type checking via `tsc --noEmit`

### 18.2 Configuration

`.eslintrc.cjs`:

```js
module.exports = {
  root: true,
  parser: "@typescript-eslint/parser",
  parserOptions: { project: ["./tsconfig.json"], tsconfigRootDir: __dirname },
  extends: [
    "eslint:recommended",
    "plugin:@typescript-eslint/strict-type-checked",
    "plugin:react-hooks/recommended",
    "plugin:jsx-a11y/recommended",
    "prettier",
  ],
  rules: {
    "@typescript-eslint/no-explicit-any": "error",
    "@typescript-eslint/consistent-type-imports": "error",
    "react-hooks/exhaustive-deps": "error",
  },
};
```

`.prettierrc`:

```json
{
  "semi": true,
  "singleQuote": false,
  "trailingComma": "all",
  "printWidth": 100,
  "tabWidth": 2
}
```

### 18.3 Pre-Commit Gate

`pnpm check` runs locally before any commit:

```bash
pnpm tsc --noEmit && pnpm eslint . && pnpm prettier --check . && pnpm test --run
```

CI runs the same. Red CI blocks merge.

### 18.4 No Style Debates

Formatting is delegated to Prettier. ESLint catches genuine bugs and anti-patterns. Do not argue about either in PRs — run the tools.

---

## 19. Common Anti-Patterns

### 19.1 Mixing Server and Client State

```tsx
// Rejected — mirroring server data into Zustand
const { data } = useSubmitQuery();
useEffect(() => {
  if (data) useAnswerStore.getState().setAnswer(data);
}, [data]);

// Correct — read directly from the query
const { data } = useSubmitQuery();
return data ? <AnswerDisplay answer={data} /> : <Loader />;
```

### 19.2 Untyped `fetch`

```tsx
// Rejected
const res = await fetch("/api/query", { ... });
const data = await res.json();

// Correct
const data = await apiClient.submitQuery(input);
```

### 19.3 `any` to Silence the Compiler

```tsx
// Rejected
const handleClick = (e: any) => { ... };

// Correct
const handleClick = (e: React.MouseEvent<HTMLButtonElement>) => { ... };
```

### 19.4 useEffect for Derived State

```tsx
// Rejected
const [fullName, setFullName] = useState("");
useEffect(() => setFullName(`${first} ${last}`), [first, last]);

// Correct — derived state is just a variable
const fullName = `${first} ${last}`;
```

### 19.5 Index as Key

```tsx
// Rejected — breaks reconciliation on reorder/insert
{items.map((item, i) => <Row key={i} item={item} />)}

// Correct
{items.map(item => <Row key={item.id} item={item} />)}
```

### 19.6 Reading `useStore()` Without a Selector

```tsx
// Rejected — re-renders on any change
const store = useDisclaimerStore();
return store.isAccepted ? ... : ...;

// Correct
const isAccepted = useDisclaimerStore(s => s.isAccepted);
```

### 19.7 Inline Functions Recreated on Every Render in Loops

Already covered in §4.5. Use `useCallback` for handlers passed to memoized children or large lists.

### 19.8 Conditional Hooks

```tsx
// Rejected — violates rules of hooks
if (isAdmin) {
  const data = useAdminQuery();
}

// Correct — call always, gate inside the hook
const data = useAdminQuery({ enabled: isAdmin });
```

### 19.9 Hardcoded Backend URLs

```tsx
// Rejected
fetch("http://localhost:8000/api/query")

// Correct
fetch(`${env.VITE_API_BASE_URL}/api/query`)
```

### 19.10 Bypassing the Type System

```tsx
// Rejected
const data = response as QueryResponse;

// Correct
const data = QueryResponseSchema.parse(response);
```

---

## 20. Library-Specific Notes

### 20.1 shadcn/ui

- Components are copied source, not a package. Re-running the CLI overwrites your changes — keep customizations in mind before doing so.
- The `components.json` file tracks aliases and config. Do not edit it manually.
- For new components, run `pnpm dlx shadcn-ui@latest add <name>` and review the diff before committing.

### 20.2 Zustand

- Always wrap stores in `create<StoreType>()` (with the explicit `<T>()` syntax) to get correct types.
- Use the `persist` middleware for storage; never write to `localStorage` directly.
- Stores are not React state — they exist outside the component tree. Avoid using them for state that should reset on unmount.

### 20.3 TanStack Query

- `staleTime` is the most important config — set it to a sensible default (60s for admin metrics, 0 for query submissions).
- Use `enabled` to gate queries that need other data to fire.
- For mutations, use `onSuccess` to invalidate related queries, not manual cache pokes.

### 20.4 React Hook Form

- Use `Controller` for shadcn/ui form components (they use `forwardRef` but the integration with RHF wants a controlled wrapper).
- Watch out for `defaultValues` — uncontrolled-to-controlled warnings come from undefined defaults. Always provide defaults that match the schema's nullability.

### 20.5 Cloudflare Turnstile

- The `@marsidev/react-turnstile` component handles widget lifecycle.
- Use the test site key locally (`1x00000000000000000000AA`) so dev doesn't depend on Cloudflare.
- The token is single-use and expires after ~5 minutes — refresh before submission if approaching expiry.

### 20.6 Vite

- HMR is enabled by default; do not export non-component values from component files (it breaks Fast Refresh).
- Use `import.meta.env` only in `src/config/env.ts`.
- The build output goes to `dist/` — committed via SWA's GitHub Action, not stored in git.

---

## Quick Reference Card

When in doubt, ask:

1. Does `tsc --strict` pass on this file?
2. Did I put server state in TanStack Query, or did I leak it into Zustand?
3. Does this component name describe what it IS, not what it does?
4. Can a screen reader and a keyboard-only user complete this flow?
5. Did I validate the API response with Zod, or did I `as`-cast?
6. Did I use Tailwind classes only, or did I sneak in inline styles?
7. Did I handle every `ApiError.code` with an exhaustive switch?
8. Is the bundle still under 200KB gzipped?

If any answer is "no", fix it before opening a PR.

---

*End of frontend agent guide. Last updated: extended CitationSchema with source_url, pdf_url, court, and year fields to support the dual-format corpus (HTML primary, PDF archival) — citation cards now expose both an Indian Kanoon link and an authoritative PDF download link. Update this file when conventions change — and update the code to match.*
