# apps/web — agent guide

Next.js 16 App Router, React 19, TypeScript, Tailwind v4, shadcn/ui, NextAuth v5.

## Layout

```
app/
  (auth)/          login + signup pages + server actions (bcrypt, raw pg)
  (authed)/        portfolio, trade, trades — require an auth() session
  api/auth/        NextAuth handler
  markets/         sortable symbol table
  stocks/[ticker]/ chart + indicators + news per ticker
  compare/         multi-ticker normalized chart
  news/, recommendations/
  layout.tsx       SiteHeader + SiteFooter wrap every route
auth.ts            NextAuth v5 setup (credentials provider, bcrypt)
auth.config.ts     Edge-safe config (no node-only imports)
proxy.ts           NextAuth middleware
components/
  ui/              shadcn-generated primitives — don't hand-edit
  *.tsx            site-header, site-footer, price-chart, etc.
lib/
  api/             fetch client for FastAPI. client.ts = public, server.ts = authed.
  db.ts            raw pg pool (only used by the credentials provider)
  users.ts         user lookup/create for credentials auth
  utils.ts         cn() helper
types/next-auth.d.ts  augments Session.user with id
sentry.*.config.ts    Sentry init per runtime; no-op without DSN
instrumentation.ts    Next 15+ hook that loads the right sentry config
```

## Two API clients — pick the right one

- `lib/api/client.ts` → `apiGet<T>(path)` — **public** endpoints, callable from
  server components or the browser. No auth header.
- `lib/api/server.ts` → `authedGet/authedPost` — **server-only**, marked with
  `import "server-only"` so it can't accidentally leak into a client bundle.
  Reads `auth()`, attaches `X-Internal-Token` + `X-User-Id`. Use for anything
  that mutates per-user data (`/v1/portfolio`, `/v1/trades`, etc.).

If you need an authenticated call from a client component, route it through
a server action or a route handler — never through the browser.

## NextAuth specifics

- v5 beta. `auth()` is the server-side session reader; use it in server
  components and `authedFetch`.
- Credentials provider only — Google/GitHub OAuth was deferred past Phase 3.
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

## Sentry

`instrumentation.ts` → `sentry.server.config.ts` (Node) or `sentry.edge.config.ts`
(Edge). `instrumentation-client.ts` → browser. All three early-return if their
DSN env var is empty, so `pnpm dev`/`pnpm build` work offline.

## Conventions

- shadcn components go in `components/ui/`. To add one: `pnpm dlx shadcn@latest add <name>`.
- Use Tailwind utilities; the existing v1 palette (dark + gold accent) is captured
  in `app/globals.css` via CSS variables.
- Charts use `lightweight-charts` v5. The wrapper lives in
  `components/price-chart.tsx`; reuse it rather than instantiating a chart inline.
- Server components by default — only mark `"use client"` when you need state,
  effects, or interactivity.
