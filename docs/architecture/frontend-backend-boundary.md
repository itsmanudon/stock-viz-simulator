# The frontend/backend boundary

Where code runs in this app is a **security boundary**, not just a
performance choice. Next.js App Router makes that boundary easy to cross
by accident, so StockViz enforces it structurally.

## Three execution contexts

| Context | Runs on | Can read secrets? | Marked by |
| --- | --- | --- | --- |
| Server component | Server, per request | **Yes** | Default — no directive |
| Client component | Browser (and SSR pass) | **No** | `"use client"` |
| Route handler / server action | Server | **Yes** | `app/api/**/route.ts` |

**Server components are the default.** `"use client"` is added only when
state, effects, or interactivity are needed — which keeps the secret-bearing
surface small by default rather than by discipline.

## Two API clients, deliberately separate

```
lib/api/client.ts   → apiGet()                    public endpoints, either context
lib/api/server.ts   → authedGet() / authedPost()  server-only, per-user data
```

`server.ts` opens with:

```ts
import "server-only";
```

That package has no runtime behaviour — it exists to **fail the build** if
the module is ever pulled into a client bundle. Ten modules in `lib/` carry
it (`trading.ts`, `options.ts`, `alerts.ts`, `replay.ts`, …).

**This is the pattern worth taking away:** `INTERNAL_API_TOKEN` leaking to
the browser would let anyone mint a bridge token for any user. Rather than
relying on review to catch a bad import, the leak is made impossible to
compile.

## The two-base-URL split

```ts
const SERVER_BASE  = process.env.API_URL ?? "http://127.0.0.1:8000";
const BROWSER_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

function baseUrl(): string {
  return typeof window === "undefined" ? SERVER_BASE : BROWSER_BASE;
}
```

The same public client works in both contexts because it picks its base at
call time. `API_URL` is runtime and can be cluster DNS; `NEXT_PUBLIC_API_URL`
is inlined at build time and must be browser-reachable. See
[networking](../infrastructure/networking.md).

## How a client component reaches per-user data

It cannot call the API directly — the bridge is server-only. The route is:

```
Client component  →  fetch("/api/alerts")  →  Next route handler
                                              → auth()  (session)
                                              → listAlerts()  (mints bridge JWT)
                                              → FastAPI /v1/alerts
```

`app/api/alerts/route.ts` exists precisely for the polling alert bell. It
re-checks the session itself rather than trusting the caller:

```ts
const session = await auth();
if (!session?.user?.id) return NextResponse.json({ alerts: [] }, { status: 401 });
```

The rule from `apps/web/CLAUDE.md`: *if you need an authenticated call from
a client component, route it through a server action or a route handler —
never through the browser.*

## Retry policy encodes idempotency

`lib/api/client.ts` retries transient failures with exponential backoff —
the API runs on Render's free tier, which spins down after ~15 minutes and
takes 30–60 s to cold start, so 502/503/504 and connection resets are
normal rather than exceptional.

But:

```ts
export async function apiPost<T>(path, body, opts = {}) {
  // Writes are not retried by default: a POST that timed out may still have
  // been applied server-side, and replaying it could duplicate a trade.
  return request<T>(path, {...}, { ...opts, maxAttempts: opts.maxAttempts ?? 1 });
}
```

**GET retries, POST does not.** A timed-out POST may already have committed
server-side; the client cannot distinguish "never arrived" from "arrived,
response lost". With no idempotency key on the trade endpoint, retrying
could execute a trade twice.

The authenticated client (`server.ts`) has no retry loop at all — every
authed call is a single `fetch`.

This is the correct application of a general rule: **retry only what is
idempotent.** The right way to make writes retryable would be an
idempotency key on the request, which this API does not have.

## Caching

```ts
cache?: RequestCache;          // defaults to "no-store"
revalidateSeconds?: number;    // Next data cache
tags?: string[];               // for revalidateTag() after a mutation
```

Default is `no-store` so server components see fresh data; EOD data changes
once a day, so callers opt into `revalidateSeconds` where staleness is
acceptable. Tags let a mutation invalidate exactly the affected entries.

Fresh-by-default with opt-in caching is the safer direction — a stale
portfolio balance is a bug, a stale symbol list is not.

## Route groups

```
app/(public)/     marketing, login, signup — public header and footer
app/(product)/    guest-capable research routes + the workstation shell
  (authed)/       dashboard, portfolio, trade, orders, watchlist, alerts
app/api/          route handlers
```

Parenthesised segments group without affecting the URL, so each group owns
its own chrome. `(authed)` is protected by `proxy.ts` (Edge middleware),
which is why `auth.config.ts` is split from `auth.ts` — Edge cannot import
bcrypt's Node `crypto`.

**Middleware is not the only guard.** Every `/v1` call still verifies the
bridge JWT server-side, so a bypassed middleware yields a 401 from FastAPI
rather than data. Two independent layers.

## Checklist for a new authenticated page

1. Server component by default.
2. Fetch through `lib/api/<resource>.ts` using `authedGet`/`authedPost`.
3. Ensure the module carries `import "server-only"`.
4. Place the route under `app/(product)/(authed)/`.
5. If a client component needs the data, pass it as props — or add a route
   handler that re-checks `auth()`.
6. Never read `INTERNAL_API_TOKEN` outside a `server-only` module.
