# StockViz — local setup

Step-by-step setup for the StockViz monorepo. Commands are given for **macOS / Linux**
(bash/zsh) and **Windows** (PowerShell). Pick the column that matches your shell.

## Prerequisites

| Tool        | Version | macOS / Linux                                                    | Windows                                                   |
| ----------- | ------- | ---------------------------------------------------------------- | --------------------------------------------------------- |
| Node.js     | 22+     | `brew install node@22` (or [nvm](https://github.com/nvm-sh/nvm)) | [nvm-windows](https://github.com/coreybutler/nvm-windows) |
| pnpm        | 11+     | `npm install -g pnpm`                                            | `npm install -g pnpm`                                     |
| Python + uv | 3.12+   | `brew install uv`                                                | `winget install --id=astral-sh.uv`                        |
| Docker      | latest  | Docker Desktop for Mac                                           | Docker Desktop for Windows                                |

Verify with:

```bash
node -v && pnpm -v && uv --version && docker --version
```

## 1. Clone and install dependencies

### macOS / Linux

```bash
git clone https://github.com/itsmanudon/stock-viz-simulator.git
cd stock-viz-simulator
pnpm install
uv --directory apps/api sync
```

### Windows (PowerShell)

```powershell
git clone https://github.com/itsmanudon/stock-viz-simulator.git
cd stock-viz-simulator
pnpm install
uv --directory apps/api sync
```

## 2. Configure environment files

Copy the example files. Defaults are wired to `infra/docker-compose.yml`, so
local dev works without edits.

### macOS / Linux

```bash
cp apps/web/.env.example apps/web/.env.local
cp apps/api/.env.example apps/api/.env
```

### Windows (PowerShell)

```powershell
Copy-Item apps/web/.env.example apps/web/.env.local
Copy-Item apps/api/.env.example apps/api/.env
```

### Values you may want to change

- **`INTERNAL_API_TOKEN`** — must match between `apps/web/.env.local` and
  `apps/api/.env`. The default `dev-internal-token-change-me` works locally.
- **`AUTH_SECRET`** (web) — NextAuth session signing. Generate with
  `openssl rand -base64 32`. The committed dev default is fine for local use.
  (`NEXTAUTH_JWT_SECRET` on the API is unused leftover; you can leave the
  example value.)
- **`ALPHA_VANTAGE_KEY`**, **`NEWSDATA_KEY`** — optional. Ingest services
  short-circuit gracefully when these are blank.
- **`SENTRY_DSN`** / **`NEXT_PUBLIC_SENTRY_DSN`** — leave blank; both apps
  no-op without a DSN.

> **Note (Windows IPv6 quirk):** keep `127.0.0.1` instead of `localhost` in env
> defaults — Windows IPv6 lookups can bypass the Docker container otherwise.

> **Note (port collisions):** Next.js auto-bumps to the next free port (e.g.
> `:3001`, `:3005`) if `:3000` is held. The dev setup is port-agnostic —
> `AUTH_URL` is intentionally **unset** in dev (NextAuth trusts the request
> host when `NODE_ENV !== "production"`), so whichever port Next picks just
> works. Only set `AUTH_URL` in production.

## 3. Boot Postgres + Adminer

```bash
pnpm db:up
```

This runs `docker compose -f infra/docker-compose.yml up -d`, binding
Postgres to **`127.0.0.1:5434`** (not 5432, to avoid clashing with a native
install) and Adminer to `:8080`.

## 4. Apply migrations and seed

Same on both platforms:

```bash
uv --directory apps/api run alembic upgrade head
uv --directory apps/api run python -m stockviz.cli seed
uv --directory apps/api run python -m stockviz.cli backfill
```

`backfill` is a one-time CSV → DB import; `seed` populates the symbol list.

## 5. Run the two dev servers

Open two terminals.

### Terminal 1 — FastAPI

```bash
pnpm api:dev          # uvicorn --reload on http://127.0.0.1:8000 (fixed port)
```

### Terminal 2 — Next.js

```bash
pnpm dev:web          # turbopack on http://localhost:3000 (or the next free port)
```

Visit:

- App: <http://localhost:3000>
- OpenAPI docs: <http://127.0.0.1:8000/docs>
- Adminer: <http://localhost:8080> (server `postgres`, user/pass/db `stockviz` / `stockviz_dev` / `stockviz`)

## Ports

| Service       | Port                |
| ------------- | ------------------- |
| Web (Next.js) | 3000 (or next free) |
| API (FastAPI) | 8000                |
| Postgres      | 5434                |
| Adminer       | 8080                |
| Kafka (optional, `pnpm events:up`) | 9092 |

Optional event stack (KRaft Kafka, not required to trade):

```bash
pnpm events:up
pnpm events:publisher            # or: python -m stockviz.cli publish-outbox --once
pnpm events:market-ingest
pnpm events:market-analytics
pnpm events:news-ingest
pnpm events:news-sentiment
pnpm events:sentiment-aggregate
```

See [`EVENT_DRIVEN_ARCHITECTURE.md`](./EVENT_DRIVEN_ARCHITECTURE.md).
Topics `stockviz.trades.v1`, `stockviz.market.v1`, and `stockviz.news.v1`
are created explicitly (auto-create is disabled).

## Quality gates

These mirror what CI runs on every push/PR to `dev` and `main`:

```bash
pnpm lint                                  # biome (web) + ruff (api)
pnpm typecheck                             # tsc + pyright
uv --directory apps/api run pytest
pnpm build                                 # production build of the web app
```

## E2E tests (Playwright)

End-to-end tests live in `apps/web/tests/e2e/` and use
[Playwright](https://playwright.dev/).

### First-time setup

Install the Chromium browser binary (one-off, not stored in node_modules):

```bash
pnpm --filter @stockviz/web exec playwright install --with-deps chromium
```

### Running tests

E2E tests run against a **production build** of the web app, so you need:

1. Both servers running (`pnpm api:dev` + `pnpm dev:web` → or let Playwright
   handle Next.js automatically)
2. The database seeded (`pnpm api:migrate` + CLI seed/backfill)

With both servers already running on their default ports:

```bash
pnpm e2e                   # all suites, Chromium, headless
pnpm --filter @stockviz/web e2e:ui   # interactive Playwright UI
```

If neither server is running, Playwright will start a production Next.js
server automatically (`pnpm start`), but you still need the FastAPI process
running separately.

### Test suites

| File              | Coverage                                              |
| ----------------- | ----------------------------------------------------- |
| `markets.spec.ts` | `/markets` loads and rows are clickable (no auth)     |
| `auth.spec.ts`    | Sign-up flow + protected-route redirect               |
| `trade.spec.ts`   | Place a buy order; verify it appears in trade history |

CI runs the full E2E suite in the `e2e` job (see `.github/workflows/ci.yml`).

## Common issues

- **Postgres connection refused** — ensure `pnpm db:up` has finished and that
  nothing else is bound to `:5434` (`lsof -i :5434` on macOS, `netstat -ano | findstr 5434` on Windows).
- **Auth errors hitting `/v1`** — check that `INTERNAL_API_TOKEN` is identical
  in `apps/web/.env.local` and `apps/api/.env`.
- **`pnpm dev:web` lands on a different port** — port 3000 is taken by
  another process. No action needed: `AUTH_URL` is unset in dev so NextAuth
  derives URLs from the request host on whatever port Next picks.
- **Alembic can't import `stockviz`** — run from the repo root and use
  `uv --directory apps/api run alembic ...`; the `prepend_sys_path=src` in
  `alembic.ini` only works in that context.

## Deployment

See [`DEPLOYMENT.md`](./DEPLOYMENT.md) for Vercel (web) and Render (api + db)
setup. There is no separate cron service — daily refresh is in-process
APScheduler. Current constraints are in [`KNOWN_LIMITATIONS.md`](./KNOWN_LIMITATIONS.md).
