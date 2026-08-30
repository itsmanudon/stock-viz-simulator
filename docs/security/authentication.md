# Authentication and authorization

Two distinct mechanisms, and conflating them is the usual source of
confusion:

| Boundary | Mechanism | Where |
| --- | --- | --- |
| Browser ↔ Next.js | NextAuth v5 session (JWT cookie) | `apps/web/auth.ts` |
| Next.js ↔ FastAPI | Short-lived HS256 bridge JWT | `apps/web/lib/api/server.ts` → `stockviz/auth.py` |

**The browser never holds an API credential.** It holds a session cookie;
the Next.js *server* holds the shared secret and mints a fresh bridge
token per call.

## User authentication (browser ↔ web)

`apps/web/auth.ts` configures two providers:

- **Credentials** — email + password, validated with a Zod schema
  (`email().max(320)`, password 8–128), verified against `password_hash`
  with `bcrypt.compare`. A missing user and a wrong password both return
  `null`, so the response does not distinguish them.
- **Google OAuth** — `findOrCreateOAuthUser` maps the provider identity to
  a database user, and the `jwt` callback stores **our** database id in
  `token.sub`.

That last point matters: downstream, `sub` is always the StockViz
`users.id`, never a provider-specific identifier.

Because the credentials provider uses bcryptjs (Node `crypto`), `auth.ts`
cannot be imported from Edge contexts. Middleware uses the providers-free
`auth.config.ts` instead.

## The service bridge (web ↔ api)

```ts
// apps/web/lib/api/server.ts — server-only
new SignJWT({ sub: userId })
  .setProtectedHeader({ alg: "HS256" })
  .setIssuedAt()
  .setExpirationTime("60s")
  .sign(signingKey());
```

```python
# apps/api/src/stockviz/auth.py
payload = jose_jwt.decode(token, settings.internal_api_token, algorithms=["HS256"])
return int(payload["sub"])
```

Four deliberate properties:

| Property | Why |
| --- | --- |
| `import "server-only"` | Importing the module client-side is a **build error**, not a review catch |
| Signed `sub` claim | The user id is covered by the signature and cannot be altered without the secret |
| 60-second expiry | Bounds the replay window if a token leaks from a log or proxy |
| `algorithms=["HS256"]` pinned | Blocks `alg: none` and algorithm-confusion attacks |

### What this replaced, and why

The earlier bridge sent `X-Internal-Token` (a shared secret) plus
`X-User-Id` (a plain header). Anyone who obtained the token could
impersonate **any** user by changing a number in a header — the token
proved *service* identity but said nothing about *which user* the request
was for. Moving the user id into a signed claim binds the two together.

Docs or comments mentioning those headers are historical.

Covered by `apps/api/tests/test_auth_bridge.py`: wrong-secret rejection,
expiry enforcement, `alg: none`, missing/non-numeric `sub`, and malformed
headers.

## Authorization

There are no roles. Authorization is **ownership**, applied consistently
in every authenticated router:

| Pattern | Example |
| --- | --- |
| Scope the query by `user_id` | `alerts.py`, `watchlist.py`, `options.py` |
| Load then compare, 404 on mismatch | `trading.py::get_trade_execution`, `alerts.py::delete_alert` |
| Resolve through the user's portfolio | `orders.py`, `trading.py` |

`get_trade_execution` returns **404, not 403**, for a trade the caller
does not own — so the endpoint does not confirm that another user's trade
id exists.

**There is no admin surface.** No endpoint accepts a `user_id` parameter;
identity comes only from the verified `sub` claim. That removes the
largest IDOR surface by construction.

## Secrets

| Secret | Used by | Guard |
| --- | --- | --- |
| `INTERNAL_API_TOKEN` | Both — **must be identical** | Both apps refuse to boot in production with the committed dev default |
| `AUTH_SECRET` | Web — NextAuth session signing | Same |
| `GOOGLE_CLIENT_*` | Web — OAuth | Optional; email/password works without |
| `ANTHROPIC_API_KEY`, `NEWSDATA_KEY`, `ALPHA_VANTAGE_KEY` | API | Absent = feature no-ops |

Both sides implement the same refusal, independently:

```ts
// apps/web/lib/env.ts
if (value === DEV_DEFAULTS[name]) throw new Error(`${name} is still the development default…`);
```

`settings.py::_reject_dev_secrets_in_production` is the API's mirror.

The subtlety in `lib/env.ts` is worth knowing: `next build` runs
page-data collection with `NODE_ENV=production`, but **a build is not a
deploy** — CI builds with the committed dev defaults and must keep
working. So the check exempts `NEXT_PHASE === "phase-production-build"`
and enforces only at runtime.

See [secrets.md](./secrets.md) for handling and rotation.

## Rate limiting

`limiter.py::client_key` keys per authenticated user where possible, then
the left-most `X-Forwarded-For` hop, then the socket address. Uvicorn runs
with `--proxy-headers`.

Public reads are limited (60/min; 30/min screener, 20/min backtest, 10/min
SSE). **Authenticated routers are deliberately not slowapi-limited** —
every authed request arrives from the Next.js server, so a per-IP limit
would be one global bucket. Per-user throttling is done in the router
where it matters (`comments.py`: 5 posts/min via a DB count).

**Limitation:** storage is in-memory, so limits are per-process. With the
API HPA at `maxReplicas: 5`, the effective budget is up to 5×, and it
resets on restart. See [ADR-0004](../adr/ADR-0004-no-redis.md).

## Known gaps

- No email verification, password reset, or change-password flow.
- No account lockout or brute-force throttling on the credentials
  provider — bcrypt cost is the only barrier.
- No CSRF token beyond NextAuth's own protections.
- No token revocation; the bridge JWT is valid for its full 60 s.
- No `aud`/`iss` claims on the bridge token — acceptable because the
  secret has exactly one purpose, but it means the token is not scoped
  to a particular API if that ever changed.

See [threat-model.md](./threat-model.md).
