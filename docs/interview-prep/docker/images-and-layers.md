# Docker: layers, one image many commands, and env timing

> **Before this note:** read [Docker](../../infrastructure/docker.md).
> **Source:** `apps/api/Dockerfile`, `apps/web/Dockerfile`,
> `infra/docker-compose.yml`.

Three transferable ideas, each with a concrete bug behind it.

## 1. Layer ordering is cache design

```dockerfile
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev   # dependencies only
COPY src ./src
RUN uv sync --frozen --no-dev                        # then the project
```

Docker caches layer-by-layer and invalidates **everything after** the first
changed layer. Dependencies change rarely; source changes constantly. So
dependencies must be installed *before* source is copied.

Reversed, every one-line source edit would reinstall the full dependency
tree. The two-step `uv sync` exists purely to create that boundary.

**General rule:** order layers from least to most frequently changed.

`--mount=type=cache,target=/root/.cache/uv` is the complement: a BuildKit
cache mount persists across builds without becoming part of any layer, so
the image stays small *and* rebuilds stay fast.

## 2. One image, many commands

The API image is the runtime for **ten** workloads: the API, the migration
Job, the scheduler, the outbox publisher, and six consumers. Each
Kubernetes Deployment overrides `command`.

| | One image | Image per workload |
| --- | --- | --- |
| Version skew | Impossible | Possible |
| CI build/scan | One artifact | Ten |
| Image size | Largest common set | Minimal each |
| Registry storage | One set of layers | Ten |

At this size the trade is clearly right: a worker cannot drift from the
API, and there is one thing to build, scan, and promote.

### The `CMD` trap this creates

The default `CMD` runs migrations then serves:

```dockerfile
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn ..."]
```

Correct for **Render** (one instance, no release-command hook on the free
tier). Actively wrong for Kubernetes, where five API replicas would race on
the schema — which is why migrations are a separate Job and every workload
overrides the command. The Dockerfile says so in a comment:
*"Kubernetes MUST override this CMD so API replicas do not all migrate."*

**The `exec` matters.** Without it, `sh` remains PID 1 and forwards
nothing, so **SIGTERM never reaches uvicorn** — the pod would be SIGKILLed
after `terminationGracePeriodSeconds: 30` instead of draining. This is the
classic "why doesn't my container shut down gracefully?" bug, and it also
makes the graceful-shutdown handlers in `dispatcher.py::run_loop`
meaningless if you get it wrong.

## 3. Build-time vs runtime environment

```dockerfile
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}
```

| Variable | Resolved | Changeable by |
| --- | --- | --- |
| `NEXT_PUBLIC_API_URL` | **Build time** — inlined into the JS bundle | Rebuilding the image |
| `API_URL` | **Runtime** — read by the Node server | Redeploying |

A wrong `NEXT_PUBLIC_*` cannot be fixed with a new env var; the value is
already baked into JavaScript the browser downloads. That surprises people,
and it is the reason the two must differ in Kubernetes: the server uses
cluster DNS, the browser cannot.

**General rule:** anything shipped to a client is build-time
configuration. Treat it like code, not config.

## Two real deployment bugs worth telling

### `HOSTNAME` collision

```dockerfile
CMD ["sh", "-c", "export HOSTNAME=0.0.0.0; exec node apps/web/server.js"]
```

Next's standalone server binds to `process.env.HOSTNAME`. **Kubernetes
sets `HOSTNAME` to the pod name.** So the server tries to bind to
`stockviz-web-7d4f...`, and probes to the pod IP fail — a failure that
presents as a networking or probe problem and is actually two systems
overloading one variable name.

### pnpm's isolated layout vs Next tracing

```dockerfile
RUN printf 'node-linker=hoisted\n' > .npmrc
```

pnpm's default isolated `node_modules` leaves `@swc/helpers` as a nested
symlink that Next's standalone tracing doesn't copy. The image builds
cleanly and crashes on boot with `MODULE_NOT_FOUND`.

Note the scope: hoisting is applied **only inside the image**, so local
development keeps the isolated layout. A build-time workaround that doesn't
change developer behaviour.

And the guard rail against exactly this class of failure:

```dockerfile
RUN test -f apps/web/.next/standalone/apps/web/server.js
```

**Assert your build output.** A silently incomplete build otherwise
produces an image that passes CI and fails on boot.

## Security defaults

| Practice | Present | Why it matters |
| --- | --- | --- |
| Multi-stage | ✅ | Build tools (uv, pnpm, compilers) never reach runtime |
| Non-root uid 10001 | ✅ | Matches `runAsUser` in the k8s securityContext |
| Slim base | ✅ | Smaller attack surface |
| Pinned tags | ✅ | `python:3.12-slim`, `node:22-bookworm-slim` |
| Digest pinning | ❌ | Tags can move |
| Image scanning | ❌ | Deps are audited; base OS packages are not |

Matching the container uid to the Kubernetes `runAsUser` is a detail worth
noticing — a mismatch produces permission errors that look like application
bugs.

## Interview questions

**Foundation — "Why multi-stage builds?"**
> The build stage needs compilers and package managers; the runtime doesn't.
> Multi-stage copies only the artifact, so the final image is smaller and
> has less attack surface.

**Foundation — "Why copy the lockfile before the source?"**
> Cache. Docker invalidates every layer after the first changed one.
> Dependencies change rarely and source changes constantly, so installing
> dependencies first keeps that expensive layer cached.

**Strong SWE — "You use one image for ten workloads. Defend it."**
> No version skew between API and workers, and one artifact to build, scan,
> and promote. The cost is an image larger than any single workload needs.
> Each Deployment overrides `command`; the default `CMD` migrates-then-serves
> for Render, and Kubernetes must override it or five replicas race on the
> schema.

**Strong SWE — "Your container ignores SIGTERM. Why?"**
> Almost always a shell as PID 1 without `exec`. `sh -c "cmd"` doesn't
> forward signals, so the app never sees SIGTERM and gets SIGKILLed after
> the grace period. `exec` replaces the shell so the app is PID 1.

**Advanced — "You set the wrong API URL in production. Can you fix it with an env var?"**
> Depends which. `API_URL` is runtime — redeploy and it's fixed.
> `NEXT_PUBLIC_API_URL` is inlined into the browser bundle at build time,
> so it needs a rebuild. Anything shipped to the client is build-time
> config.

**Advanced — "Your image built fine and crashed on boot. How do you stop that recurring?"**
> That happened — pnpm's isolated layout left a package Next's standalone
> tracing didn't copy. I added `RUN test -f .../server.js` so the build
> asserts its own output rather than producing an image that fails later.

## Memorise vs understand

**Memorise:** least-changing layers first; `exec` for signals; `NEXT_PUBLIC_*`
is build-time; multi-stage keeps build tools out of runtime.

**Understand:** why one image for many workloads beats ten images here; why
a shell PID 1 breaks graceful shutdown; why asserting build output is worth
a line.
