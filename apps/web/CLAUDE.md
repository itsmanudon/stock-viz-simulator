# apps/web — agent guide

Next.js 16 App Router, React 19, TypeScript, Tailwind v4, shadcn/ui, NextAuth v5.

## Layout

```
app/
  (public)/        marketing home, login, signup, sign-in-required; owns the
                   concise public header and traditional website footer
  (product)/       guest-capable research routes plus the workstation shell
    (authed)/      dashboard, portfolio, trade, trades, orders, watchlist,
                   alerts, settings — protected by proxy.ts. `/dashboard` is
                   the signed-in home: a bento grid of portfolio widgets fed by
                   `lib/dashboard-data.ts` (every widget but the portfolio hero
                   degrades to its own empty state if its request fails).
                   Portfolio and trade show reserved
                   vs available cash/shares from pending orders. `/trade` is
                   the execution workstation; `/stocks/[ticker]` keeps the
                   contextual ticket. `/alerts` is alert management; the header
                   bell is compact status. Operational prices (close, trigger,
                   fill, alert target) format in the symbol-native currency.
  api/auth/        NextAuth handler
  markets/         sortable symbol table
  stocks/[ticker]/ chart + indicators + news + comments + sentiment + simulated quote badge
  compare/         Research workspace: normalized multi-ticker comparison
  screener/        filterable symbol screener
  backtest/        Research workspace: strategy experiment + equity curve
  recommendations/ Research workspace titled Signals (route unchanged)
  leaderboard/     user NAV ranking
  news/
  sign-in-required/  redirect target for unauthenticated access
  layout.tsx       document providers + skip link only; route groups own chrome
auth.ts            NextAuth v5 setup (credentials provider, bcrypt)
auth.config.ts     Edge-safe config (no node-only imports)
proxy.ts           NextAuth middleware
components/
  dashboard/       signed-in home widgets (hero, movers, orders, alerts,
                   watchlist, allocation) + the shared WidgetCard/DeltaPill
  ui/              shadcn-generated primitives — don't hand-edit
  *.tsx            app-shell/sidebar/navigation, global-ticker-search,
                   public-header, price-chart, order-ticket, backtest-form, etc.
lib/
  api/             fetch client for FastAPI, one module per resource
                   (client.ts = public, server.ts = authed, types.ts = shared types)
  db.ts            raw pg pool (only used by the credentials provider)
  users.ts         user lookup/create for credentials auth
  utils.ts         cn() helper
tests/e2e/         Playwright specs (shell, auth, markets, trade)
tests/unit/        Vitest (shell/navigation/search, csv, tables, guards, rate-limit)
types/next-auth.d.ts  augments Session.user with id
sentry.*.config.ts    Sentry init per runtime; no-op without DSN
instrumentation.ts    Next 15+ hook that loads the right sentry config
Dockerfile            Production standalone image; build from the **repo root**
next.config.ts        `output: "standalone"` + `outputFileTracingRoot` at repo root
```

## Two API clients — pick the right one

- `lib/api/client.ts` → `apiGet<T>(path)` — **public** endpoints, callable from
  server components or the browser. No auth header.
- `lib/api/server.ts` → `authedGet/authedPost` — **server-only**, marked with
  `import "server-only"` so it can't accidentally leak into a client bundle.
  Reads `auth()`, mints a short-lived HS256 JWT (`jose`, `{ sub: user.id }`,
  60 s expiry) signed with `INTERNAL_API_TOKEN`, and sends it as
  `Authorization: Bearer <token>`. Use for anything that reads or mutates
  per-user data (`/v1/portfolio`, `/v1/trades`, `/v1/orders`, `/v1/options`,
  `/v1/watchlist`, `/v1/alerts`, ...).

If you need an authenticated call from a client component, route it through
a server action or a route handler — never through the browser.

## NextAuth specifics

- v5 beta. `auth()` is the server-side session reader; use it in server
  components and `authedFetch`.
- Providers: **Credentials** (email + password, bcrypt) and **Google OAuth**
  (needs `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET`; see `.env.example`).
- Sessions are JWT (default). The user.id is persisted via the `jwt` callback
  and surfaced via the `session` callback (see `auth.ts`).
- `proxy.ts` runs as Edge middleware. Keep node-only imports out of the files
  it transitively imports (that's why `auth.config.ts` is split from `auth.ts`).

## Build/run

```powershell
pnpm dev:web              # turbopack dev server on :3000 (or :3001)
pnpm --filter @stockviz/web build
pnpm --filter @stockviz/web lint     # biome
pnpm --filter @stockviz/web typecheck
```

The build runs `next build` with Turbopack. If `SENTRY_AUTH_TOKEN` is set,
`withSentryConfig` uploads source maps; otherwise it's a plain build.

`next.config.ts` sets `output: "standalone"` so `apps/web/Dockerfile` can
copy `.next/standalone` into a slim Node image (`CMD node apps/web/server.js`).
Build from the repository root:

```powershell
docker build -f apps/web/Dockerfile --build-arg NEXT_PUBLIC_API_URL=http://localhost:8000 -t stockviz-web:dev .
```

`NEXT_PUBLIC_API_URL` is inlined into the **browser** bundle at image build.
For kind port-forward it must be a URL the laptop can reach (typically
`http://localhost:8000`). Cluster DNS such as `http://stockviz-api:8000` is
not reachable from the browser. Server-side fetches use runtime `API_URL`
(the web Deployment sets `http://stockviz-api:8000`).

Kubernetes overwrites `HOSTNAME` with the pod name. The image `CMD` exports
`HOSTNAME=0.0.0.0` before `node apps/web/server.js` so the process listens on
all interfaces. Probes use `GET /api/health` (no SSR), not the homepage.

The image `pnpm install` uses `node-linker=hoisted` so Next standalone tracing
can copy `@swc/helpers`. Isolated pnpm (the local default) omits that package
and the container crashes with `MODULE_NOT_FOUND`.

## E2E (Playwright)

```powershell
pnpm e2e                  # or: pnpm --filter @stockviz/web e2e / e2e:ui
```

Specs live in `tests/e2e/`. The Playwright `webServer` runs `pnpm start`
(production mode), so you need a build first plus the API on :8000 against a
migrated + seeded DB. Full local sequence from the repo root:

```powershell
pnpm db:up && pnpm api:migrate
uv --directory apps/api run python -m stockviz.cli seed
uv --directory apps/api run python -m stockviz.cli backfill
pnpm api:dev                          # keep running in another terminal
$env:AUTH_TRUST_HOST = "true"         # prod builds don't trust the host by default
pnpm --filter @stockviz/web build
pnpm e2e
```

`INTERNAL_API_TOKEN` and `AUTH_SECRET` must match what the API/.env uses (the
committed dev defaults already do). CI runs the same sequence — see the `e2e`
job in `.github/workflows/ci.yml`. Runs single-worker, chromium only.

## Sentry

`instrumentation.ts` → `sentry.server.config.ts` (Node) or `sentry.edge.config.ts`
(Edge). `instrumentation-client.ts` → browser. All three early-return if their
DSN env var is empty, so `pnpm dev`/`pnpm build` work offline.

## Conventions

- shadcn components go in `components/ui/`. To add one: `pnpm dlx shadcn@latest add <name>`.
- Use Tailwind utilities; the existing v1 palette (dark + gold accent) is captured
  in `app/globals.css` via CSS variables. `--*-soft` / `--*-soft-foreground`
  pairs (positive/negative/warning/neutral) are the tinted fills behind delta
  and status pills — use `DeltaPill` rather than re-rolling the chip.
  `--surface-elevated` is one step *above* `--card` (overlays: sidebar,
  popovers, sheets); `--card` is for content tiles sitting on the page.
- The type ramp adds `text-3xs` (10px) and `text-2xs` (11px) below Tailwind's
  `text-xs` for dense table meta and column labels. Use them instead of
  arbitrary `text-[10px]` / `text-[11px]`, which bypass the scale.
- Charts use `lightweight-charts` v5. The wrapper lives in
  `components/price-chart.tsx`; reuse it rather than instantiating a chart inline.
  Compare and backtest charts live in `compare-chart.tsx` and `equity-curve.tsx`.
  Canvas can't read CSS vars, so all three take their colours from
  `useChartPalette()` (`lib/chart-theme.ts`), which reads the tokens off the
  document and re-reads on theme change — never hard-code chart colours. The
  hook keeps its object identity stable while colours are unchanged because
  callers pass it to `useEffect`, and a new identity forces a full chart
  rebuild.
- Server components by default — only mark `"use client"` when you need state,
  effects, or interactivity.
- Research (`/compare`, `/backtest`, `/recommendations`) is one domain with
  three routes. See [`docs/RESEARCH.md`](../../docs/RESEARCH.md). Keep URL state
  shareable (`tickers`/`tf`, `ticker`, `min`/`signal`/`q`). Do not present
  Signals as AI advice; the engine is a seven-vote rule set.
- Operational trading (`/trade`, `/orders`, `/watchlist`, `/alerts`) is the
  authenticated execution/monitoring loop. See
  [`docs/OPERATIONAL_TRADING.md`](../../docs/OPERATIONAL_TRADING.md).
  `/trade?ticker=` prefills the ticket. `/orders?status=` is URL-backed.
  Do not describe EOD fills or alert evaluation as live exchange execution.

<!-- BEGIN:nextjs-agent-rules -->

# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` (resolved from this file's directory; in monorepos the `next` package may not be visible from the repo root) before writing any code. Heed deprecation notices.

This block is written and re-added by `next dev` — verify at `node_modules/next/dist/server/lib/generate-agent-files.js`. Removing it from a diff only re-creates the uncommitted change; committing it with your work keeps the tree clean.

<!-- END:nextjs-agent-rules -->
