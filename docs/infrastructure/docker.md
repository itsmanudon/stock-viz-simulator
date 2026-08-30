# Docker

Two images, both multi-stage, both non-root. Each carries a couple of
lessons that only show up when you actually deploy.

## The API image

`apps/api/Dockerfile` — builder installs into a virtualenv with `uv`;
runtime copies that venv into a slim base.

```dockerfile
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev   # ← dependencies only
COPY src ./src
RUN uv sync --frozen --no-dev                        # ← then the project
```

**Why two `uv sync` calls.** Dependencies change rarely; source changes
constantly. Installing dependencies before copying source means the
expensive layer is cached and only re-runs when `uv.lock` changes.
Reversing the order would reinstall every dependency on every source edit.

Other details worth knowing:

| Line | Why |
| --- | --- |
| `COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /uvx /bin/` | Pulls a pinned uv binary — no curl, no install script, reproducible |
| `--mount=type=cache,target=/root/.cache/uv` | BuildKit cache mount; survives across builds without landing in a layer |
| `COPY README.md` | `pyproject.toml` declares `readme = "README.md"`, and hatchling reads it during the wheel build |
| `UV_COMPILE_BYTECODE=1` | Precompiles `.pyc` at build time so startup doesn't pay for it |
| `useradd --uid 10001` + `USER stockviz` | Non-root, matching the `runAsUser: 10001` in the Kubernetes securityContext |

### One image, many commands

The image's default `CMD` migrates then serves:

```dockerfile
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn stockviz.main:app ... --proxy-headers ..."]
```

That is right for **Render**, which runs one instance and whose free tier
has no release-command hook. It is wrong for Kubernetes, where five API
replicas would all race on the schema — so every Kubernetes workload
**overrides the command**, and the Dockerfile lists the ten valid
commands in a comment:

```
uvicorn stockviz.main:app ...                    # API (no migrations)
alembic upgrade head                             # one-shot migrate Job
python -m stockviz.workers.scheduler             # APScheduler singleton
python -m stockviz.workers.outbox_publisher      # outbox → Kafka
python -m stockviz.workers.<consumer>            # six consumers
```

**One image, ten workloads.** The benefit is that every process runs
identical code and dependencies — a worker cannot drift from the API — and
CI builds and scans one artifact. The cost is a larger image than each
workload strictly needs, which is a good trade at this size.

Note `exec` in the CMD: without it, `sh` stays PID 1 and **SIGTERM never
reaches uvicorn**, so the pod would be SIGKILLed after the grace period
instead of shutting down cleanly.

## The web image

`apps/web/Dockerfile` — three stages (deps → builder → runtime), built
**from the repository root** because it needs the workspace lockfile.

Two hard-won details:

### `node-linker=hoisted`

```dockerfile
RUN printf 'node-linker=hoisted\n' > .npmrc
```

pnpm's default isolated layout leaves `@swc/helpers` as a nested symlink
that Next's standalone tracing does not copy. The image then crashes on
boot:

```
Cannot find module '.../node_modules/@swc/helpers/esm/_interop_require_default.js'
```

Hoisting is applied **only in this image**; local `pnpm install` keeps the
isolated layout. A build-time-only workaround, scoped so it doesn't change
developer behaviour.

### `HOSTNAME` collides with Kubernetes

```dockerfile
CMD ["sh", "-c", "export HOSTNAME=0.0.0.0; exec node apps/web/server.js"]
```

Next's standalone server binds to `process.env.HOSTNAME`. **Kubernetes
sets `HOSTNAME` to the pod name.** So the server would try to bind to
something like `stockviz-web-7d4f...`, and probes to the pod IP would
fail. Exporting `0.0.0.0` first fixes it.

This is a genuinely good interview anecdote: two systems using the same
environment variable name for different purposes, producing a failure that
looks like a networking problem and is actually a bind-address problem.

### Build-time vs runtime env

```dockerfile
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
```

`NEXT_PUBLIC_*` is **inlined into the browser bundle at build time** and
cannot be changed by redeploying with a different env var — the image
would need rebuilding. `API_URL` is read at runtime by the server. See
[networking](./networking.md#the-browser-cannot-resolve-cluster-dns).

The build also asserts its own output:

```dockerfile
RUN test -f apps/web/.next/standalone/apps/web/server.js
```

A failed trace otherwise produces an image that builds fine and crashes on
boot.

## Compose

One file, three profiles, so a developer starts only what they need:

| Command | Profile | Starts |
| --- | --- | --- |
| `pnpm db:up` | *(none)* | Postgres + Adminer |
| `pnpm stack:up` | `app` | + API and web |
| `pnpm events:up` | `events` | + Kafka (KRaft) + topic init |

Postgres uses a named volume (`stockviz_postgres_data`), so data survives
`stack:down`.

**Compose does not read `apps/api/.env`.** Provider credentials must be in
`infra/.env` or they never reach the container — and news ingest and
sentiment then silently no-op. See `infra/.env.example`.

Health-gated startup ordering (`depends_on: condition: service_healthy`)
means the API waits for Postgres to accept connections rather than
crash-looping.

## Image hygiene

| Practice | Both images |
| --- | --- |
| Multi-stage (build tools excluded from runtime) | ✅ |
| Non-root, uid 10001 | ✅ |
| Slim base | ✅ |
| Pinned base tags (`python:3.12-slim`, `node:22-bookworm-slim`) | ✅ |
| `.dockerignore` | ✅ |
| Layer ordering for cache hits | ✅ |
| Digest-pinned bases | ❌ — tags can move |
| Image scanning in CI | ❌ — deps are audited, images are not |
| SBOM / signing | ❌ |

The `docker` CI job builds both images but does not scan them. Dependency
auditing (`pnpm audit`, `pip-audit`) covers the application's own
dependencies, not the base OS packages.
