# StockViz web — production Next.js standalone image.
# Build from the repository root:
#   docker build -f apps/web/Dockerfile --build-arg NEXT_PUBLIC_API_URL=http://localhost:8000 -t stockviz-web:dev .
#
# NEXT_PUBLIC_API_URL is inlined at build time and must be a URL the *browser*
# can reach (port-forward / ingress host). Cluster DNS such as
# http://stockviz-api:8000 is not reachable from the user's laptop.
# Runtime server-side fetches use API_URL (set on the Deployment).

FROM node:22-bookworm-slim AS deps

RUN corepack enable

WORKDIR /repo

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/web/package.json apps/web/package.json

# Isolated pnpm layout leaves @swc/helpers as a nested symlink that Next
# standalone tracing does not copy. The resulting image crashes on boot:
#   Cannot find module '.../node_modules/@swc/helpers/esm/_interop_require_default.js'
# Hoist only in this image; local `pnpm install` is unchanged.
RUN printf 'node-linker=hoisted\n' > .npmrc

RUN pnpm install --frozen-lockfile --filter @stockviz/web...

FROM deps AS builder

COPY apps/web ./apps/web
RUN mkdir -p apps/web/public

ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL} \
    NEXT_TELEMETRY_DISABLED=1 \
    NODE_ENV=production

RUN pnpm --filter @stockviz/web build
RUN test -f apps/web/.next/standalone/apps/web/server.js

FROM node:22-bookworm-slim AS runtime

WORKDIR /app

RUN useradd --system --uid 10001 --create-home stockviz \
    && apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

# outputFileTracingRoot is the repo root, so standalone is rooted at /repo.
COPY --from=builder --chown=stockviz:stockviz /repo/apps/web/.next/standalone ./
COPY --from=builder --chown=stockviz:stockviz /repo/apps/web/.next/static ./apps/web/.next/static
COPY --from=builder --chown=stockviz:stockviz /repo/apps/web/public ./apps/web/public

USER stockviz
EXPOSE 3000

# Kubernetes sets HOSTNAME to the pod name. Next's standalone server listens
# on process.env.HOSTNAME, so without this override probes to the pod IP fail.
CMD ["sh", "-c", "export HOSTNAME=0.0.0.0; exec node apps/web/server.js"]
