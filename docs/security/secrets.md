# Secrets handling

## Where secrets live, per environment

| Environment | Mechanism | Encrypted at rest? |
| --- | --- | --- |
| Local dev | `apps/*/.env` with **committed dev defaults** | No — intentionally public |
| Docker Compose | `infra/.env` (gitignored) | No |
| Kubernetes (kind lab) | `Secret` manifests, **base64 in git** | **No** |
| Render | Dashboard env vars | Yes (provider-managed) |
| Vercel | Project env vars | Yes (provider-managed) |

The kind-lab secrets are base64 in git. Base64 is an encoding, not
encryption — anyone with repository access can read them. This is
acceptable **only** because those values are lab-scoped and shared with
nothing real, and it is recorded in
[KNOWN_LIMITATIONS.md](../KNOWN_LIMITATIONS.md).

## The dev-default trap, and the guard

The dev values are committed on purpose so `git clone && pnpm dev` works.
That creates one specific danger: `INTERNAL_API_TOKEN` signs the bridge
JWT whose `sub` the API trusts as the user id. If the committed default
ever reached production, **anyone could mint a token for any user**.

Both apps therefore refuse to boot in production with a known dev default
still in place — `apps/web/lib/env.ts::requireSecret` and
`settings.py::_reject_dev_secrets_in_production`. Two independent checks,
because Render and Vercel are configured separately and "set this by hand"
is exactly the step that gets missed.

Failing at startup rather than at request time is the design choice worth
noting: a misconfigured deploy is loudly broken instead of quietly
insecure.

## Generating real values

```bash
openssl rand -base64 32   # INTERNAL_API_TOKEN
openssl rand -base64 32   # AUTH_SECRET
```

`INTERNAL_API_TOKEN` **must be byte-identical** on the web and API sides.
A mismatch 401s every authenticated `/v1` call — the single most common
deployment failure in this project.

## Splitting by concern

Kubernetes splits secrets so each workload receives only what it needs:

| Secret | Consumers |
| --- | --- |
| `stockviz-db` | Everything touching Postgres |
| `stockviz-auth` | API and web only |
| `stockviz-market` | Market ingest worker |
| `stockviz-news` | News ingest worker |
| `stockviz-sentiment` | Sentiment worker |

A news worker never receives the Anthropic key. Cheap least-privilege,
done at the manifest level.

## Compose does not read `apps/api/.env`

Provider credentials must be in `infra/.env` or they never reach the
container — and news ingest and sentiment scoring then **silently no-op**.
See `infra/.env.example`.

## What is not done

- **No secret manager.** No Vault, no External Secrets Operator, no Sealed
  Secrets. Production would want one.
- **No rotation procedure.** Rotating `INTERNAL_API_TOKEN` requires
  updating both services; with 60-second tokens a rolling update produces
  a brief window of 401s. There is no documented zero-downtime rotation
  (it would need the API to accept two secrets during the overlap).
- **No secret scanning in CI.** The `security` job audits dependencies,
  not committed credentials.
- **No encryption at rest for the k8s lab.**

## If a secret leaks

1. Rotate at the provider (Render/Vercel dashboard) first.
2. Update **both** services for `INTERNAL_API_TOKEN`; expect 401s until
   both have the new value.
3. For provider API keys, revoke upstream — the value in the repo is not
   the authority.
4. Rotating `AUTH_SECRET` invalidates every active session, which is the
   desired effect if sessions may have been forged.
