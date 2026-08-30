# Security: auth bridge and threat reasoning

> **Before this note:** read
> [authentication](../../security/authentication.md),
> [secrets](../../security/secrets.md), and
> [threat model](../../security/threat-model.md).
> **Source:** `apps/web/lib/api/server.ts`, `apps/api/src/stockviz/auth.py`,
> `apps/web/lib/env.ts`, `tests/test_auth_bridge.py`.

## The design worth explaining

Two boundaries, two mechanisms:

```
Browser ──session cookie──▶ Next.js server ──signed 60s JWT──▶ FastAPI
         (NextAuth v5)                       (HS256, shared secret)
```

**The browser never holds an API credential.** The Next.js server holds
the shared secret and mints a fresh token per call.

## Why it replaced headers — the actual security argument

The previous bridge sent two headers:

```
X-Internal-Token: <shared secret>
X-User-Id: 42
```

The flaw: the token proved *service* identity but said nothing about
*which user*. Anyone who obtained it could change `42` to any number and
act as that user. The two facts weren't bound together.

Signing `sub` into the token binds them: altering the user id invalidates
the signature.

**Interview framing:** "The upgrade wasn't adding authentication — there
was already a shared secret. It was moving the user id out of an
attacker-controlled header into a signed claim."

## Four controls, and what each stops

| Control | Attack it blocks |
| --- | --- |
| HS256 signature over `sub` | Impersonation by editing the claim |
| `algorithms=["HS256"]` pinned | `alg: none` and algorithm confusion |
| 60-second expiry | Replay of a token leaked via logs or a proxy |
| `import "server-only"` | Secret reaching the browser bundle |

The last one is the most interesting engineering choice: it makes a
security property a **compile-time guarantee** rather than something code
review must catch. That is the pattern to generalise — push security
invariants into the type system or the build wherever possible.

### The `alg: none` attack

A JWT's header declares its own algorithm. A verifier that trusts that
field accepts `{"alg":"none"}` with an empty signature — the token
verifies itself. Pinning `algorithms=["HS256"]` at the call site is the
fix, and it is one line that is easy to omit.

The related attack: if a verifier accepts both HS256 and RS256, an
attacker can take the *public* RSA key and use it as an HMAC secret. Same
root cause — letting attacker-controlled data choose the verification
algorithm.

## Testing security properties

Before this iteration, the bridge's guarantees were untested. Router tests
covered the happy path plus two obvious rejections (no header, garbage
string), which means a change that dropped signature verification entirely
would have left the whole suite green.

`tests/test_auth_bridge.py` now covers wrong-secret rejection, expiry,
`alg: none`, missing and non-numeric `sub`, and malformed headers —
verified to fail when the verifier is weakened.

**The general lesson:** happy-path tests do not test security. A control
is only real if something fails when you remove it.

## Authorization: ownership, not roles

There are no roles. Every authenticated route scopes by the verified
`sub`, in one of three shapes: scope the query by `user_id`, load then
compare, or resolve through the user's portfolio.

Two details worth citing:

- **No endpoint accepts a `user_id` parameter.** Identity comes only from
  the signed claim, which removes the largest IDOR surface by
  construction rather than by discipline.
- **404, not 403,** on an ownership mismatch — so the API doesn't confirm
  that another user's resource id exists.

**Residual risk to name honestly:** the pattern is a convention, not a
type-level guarantee. A new router that forgot the check would fail no
existing test.

## Defence in depth on secrets

The dev defaults are committed on purpose so `git clone && pnpm dev`
works. That creates one specific danger, and both apps independently
refuse to boot in production with a known dev default in place.

The subtlety worth knowing: `next build` runs with
`NODE_ENV=production`, but **a build is not a deploy** — CI builds with
the committed defaults and must keep working. So the check exempts
`NEXT_PHASE === "phase-production-build"` and enforces at runtime only.
That kind of detail is what a real deployment teaches you.

## Interview questions

**Foundation — "How does your frontend authenticate to your backend?"**
> The Next.js *server* mints a 60-second HS256 JWT with the user id as
> `sub`, signed with a secret shared with FastAPI. The browser never sees
> it — the client module is `server-only`, so importing it client-side is
> a build error.

**Strong SWE — "Why not just send a shared API key?"**
> That's what it used to do, plus an `X-User-Id` header. The key proved
> service identity but not which user, so anyone with the key could change
> a header and act as anyone. Signing the user id binds the two.

**Strong SWE — "What's `alg: none` and are you vulnerable?"**
> A JWT header declares its own algorithm; a verifier that trusts it will
> accept an unsigned token. Not vulnerable — `algorithms=["HS256"]` is
> pinned at the decode call, and there's a test that constructs an
> `alg: none` token by hand and asserts a 401.

**Advanced — "Your token lives 60 seconds. Why not 5 minutes, or 1 hour?"**
> It's minted per request by a server that already has the session, so
> there's no cost to a short life — no refresh flow, no UX impact. 60
> seconds bounds the replay window if one leaks into a log or a proxy. The
> trade-off is clock skew between web and API; a minute is comfortable.

**Advanced — "Someone gets your `INTERNAL_API_TOKEN`. What can they do, and how do you recover?"**
> Full impersonation of any user against `/v1` — they can mint tokens for
> any `sub`. Recovery is rotating it on both services, and honestly
> there's no zero-downtime path today: the API accepts one secret, so a
> rolling update produces a window of 401s. Supporting two valid secrets
> during an overlap is what I'd add. That's a real gap, and it's why a
> secret manager with rotation support is high on the list.

**Advanced — "What's the weakest part of your security posture?"**
> Login throttling. There's no account lockout, no per-account rate limit,
> and no CAPTCHA on the credentials provider — bcrypt cost is the only
> barrier to credential stuffing. It's a Next.js route, so the API's
> slowapi limits don't apply to it. Second is that rate limits are
> per-process, so five replicas means five times the intended budget.
