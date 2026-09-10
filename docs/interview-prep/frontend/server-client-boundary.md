# The server/client boundary as a security boundary

> **Before this note:** read
> [The frontend/backend boundary](../../architecture/frontend-backend-boundary.md)
> and [authentication](../../security/authentication.md).

Next.js App Router lets one codebase run in two places. That is convenient
and dangerous: **an import can move a secret into the browser bundle**, and
nothing about the code looks different.

## How StockViz makes the leak impossible

```ts
// lib/api/server.ts
import "server-only";
```

`server-only` has no runtime behaviour. Its entire purpose is to **fail the
build** if the module is ever reachable from a client bundle.

Why that matters here specifically: `INTERNAL_API_TOKEN` signs the bridge
JWT whose `sub` FastAPI trusts as the user id. Leaked to the browser,
anyone could mint a token for any user. So the protection is not "reviewers
will notice a bad import" — it is a compile error.

**The transferable pattern:** when a security property can be enforced by
the type system or the build, enforce it there. Ten modules in `lib/` carry
the marker.

## Two clients, two audiences

| | `lib/api/client.ts` | `lib/api/server.ts` |
| --- | --- | --- |
| Endpoints | Public reads | Per-user data |
| Auth | None | Mints a 60 s bridge JWT |
| Callable from | Server **or** browser | Server only |
| Retries | GET yes, POST no | None |

The public client works in both contexts because it resolves its base URL
at call time:

```ts
return typeof window === "undefined" ? SERVER_BASE : BROWSER_BASE;
```

## Reaching per-user data from a client component

You cannot call FastAPI directly — the bridge is server-only. The path is a
route handler that re-checks the session:

```
Client component → fetch("/api/alerts") → route handler
                                          → auth()
                                          → listAlerts()   (mints the JWT)
                                          → FastAPI /v1/alerts
```

The route handler does not trust its caller:

```ts
const session = await auth();
if (!session?.user?.id) return NextResponse.json({ alerts: [] }, { status: 401 });
```

**Two independent guards.** Edge middleware (`proxy.ts`) protects the
`(authed)` route group, *and* every `/v1` call verifies the bridge JWT
server-side. A bypassed middleware yields a 401 from FastAPI, not data.
Middleware is a UX redirect; it is not the authorization boundary.

## Retry policy encodes idempotency — the best detail here

```ts
export async function apiPost<T>(path, body, opts = {}) {
  // Writes are not retried by default: a POST that timed out may still have
  // been applied server-side, and replaying it could duplicate a trade.
  return request<T>(path, {...}, { ...opts, maxAttempts: opts.maxAttempts ?? 1 });
}
```

GET retries with exponential backoff — Render's free tier spins down after
~15 minutes and takes 30–60 s to cold start, so transient 502/503/504 are
normal. POST does not retry at all.

The reasoning is exactly right: **a client cannot distinguish "never
arrived" from "arrived, response lost."** With no idempotency key on the
trade endpoint, a retry could execute a trade twice — real money semantics,
in a system that models money.

Note how this mirrors the backend. The Kafka pipeline is at-least-once
*because* its writes are idempotent (natural keys, inbox receipts). The
HTTP write path is at-most-once *because* its writes are not. Same
question — "is repeating this safe?" — answered differently, correctly, in
both places.

**The proper fix**, if writes needed retrying: an idempotency key on the
request, stored server-side, so a replay returns the original result. That
is what payment APIs do, and it is what this API lacks.

## Server components by default

`"use client"` is added only where state, effects, or interactivity are
needed. The security payoff is that the default is the safe context: a
component is server-side unless someone deliberately opts out, so the
surface that *could* leak a secret stays small without vigilance.

Route groups organise this:

```
app/(public)/      marketing, auth pages
app/(product)/     guest-capable research
  (authed)/        protected by proxy.ts
app/api/           route handlers
```

Parenthesised segments group without affecting the URL, so each group owns
its own chrome and protection.

## Caching defaults

Default `no-store`, with opt-in `revalidateSeconds` and cache `tags` for
targeted invalidation after a mutation.

Fresh-by-default is the safer direction: a stale portfolio balance is a
bug; a stale symbol list is not. Caching is opted into where staleness is
acceptable, rather than opted out of where it isn't.

## Interview questions

**Foundation — "Server components vs client components?"**
> Server components render on the server and can read secrets and hit the
> database directly; client components ship to the browser. Server is the
> default here — `"use client"` only where interactivity is needed.

**Strong SWE — "How do you stop an API secret reaching the browser?"**
> `import "server-only"` in every module that touches it. It has no runtime
> behaviour — it makes the build fail if the module is reachable from a
> client bundle. So it's a compile error rather than something review has to
> catch.

**Strong SWE — "A client component needs the user's alerts. How?"**
> Not directly — the bridge is server-only. It calls a Next route handler
> that re-checks `auth()` and then uses the server client. The session is
> re-verified there rather than trusted from the caller.

**Advanced — "Why do you retry GETs but not POSTs?"**
> A timed-out POST may already have committed; the client can't tell
> "never arrived" from "response lost". Without an idempotency key,
> retrying a trade could execute it twice. GETs are safe to repeat. If I
> needed retryable writes I'd add an idempotency key the server stores and
> replays.

**Advanced — "Your middleware protects `/dashboard`. Is that your authorization?"**
> No — it's a redirect for UX. Authorization is the bridge JWT that FastAPI
> verifies on every `/v1` call, plus per-route ownership checks. If
> middleware were bypassed you'd get a 401 from the API, not data.

## Memorise vs understand

**Memorise:** `server-only` fails the build; `NEXT_PUBLIC_*` is build-time;
server components are the default; GET retries, POST doesn't.

**Understand:** why compile-time enforcement beats review; why middleware
is not an authorization boundary; why the same idempotency question gets
opposite answers on the HTTP and Kafka paths.
