# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with
code in this repository.

# StockViz — agent guide

Two-app pnpm + uv monorepo. See [`README.md`](./README.md) for the current
architecture and setup, and [`docs/ENGINEERING_ROADMAP.md`](./docs/ENGINEERING_ROADMAP.md)
for the remaining honest gaps.

## Layout you'll actually touch

```
apps/web/    Next.js 16 (App Router, React 19, TS, Tailwind v4, NextAuth v5) + Playwright e2e
apps/api/    FastAPI + SQLModel + Alembic + APScheduler (Python 3.12, uv)
infra/       docker-compose (local Postgres; Kafka via `--profile events`) + render.yaml
             k8s/ (Kustomize layers: bootstrap → migrate → app → scale; Strimzi)
scripts/k8s/ kind create / build / deploy / smoke / destroy
.github/workflows/ci.yml   web, api, events-integration, security, docker, e2e
.github/workflows/k8s-smoke.yml   kind + Strimzi + migrate Job + smoke + reduced Kafka benchmark
```

Each app has its own `CLAUDE.md` with deeper notes. Skim those before editing.

## Feature surface

Beyond the original markets/charts/news/recommendations pages, the app now
includes: paper trading with **pending limit/stop orders** and **options**
(pricing, positions, expiry settlement), **dividends** and **multi-currency
FX**, **backtesting** (`/backtest`), **screener**, **leaderboard**,
**watchlists**, **price alerts**, per-ticker **comments** and **AI sentiment**
(Anthropic, optional), and a **simulated quote** ticker over **SSE**
(`/v1/stream/quotes/{ticker}` — Gaussian random walk from the latest close,
not exchange real-time data). Remaining product/ops constraints:
[`docs/KNOWN_LIMITATIONS.md`](./docs/KNOWN_LIMITATIONS.md).

News sentiment runs through a pluggable provider (Anthropic, an external HTTP
service, or off) and feeds a screener filter, a recommendation vote, and a
per-ticker series at `/v1/symbols/{ticker}/sentiment` — see
[`docs/SENTIMENT.md`](./docs/SENTIMENT.md). Compare, Backtest, and Signals
form the Research workspace; see [`docs/RESEARCH.md`](./docs/RESEARCH.md).
Trade, Orders, Watchlist, and Alerts form the operational trading loop; see
[`docs/OPERATIONAL_TRADING.md`](./docs/OPERATIONAL_TRADING.md). All live
equity paper fills (MARKET, LIMIT, STOP_LOSS, TAKE_PROFIT) go through a
pure execution kernel (`legacy_close`); cash/positions still mutate in
`apply_fill`. Successful live fills persist versioned execution provenance.
Replay sessions (`/replay`) are an isolated book over a frozen 1d
historical range; the server owns PriceBar selection. Replay Lab is
future-blind. See
[`docs/SIMULATION.md`](./docs/SIMULATION.md).

Market and news ingest are **event-driven**. APScheduler enqueues durable
outbox requests; Kafka workers fetch providers and write Postgres. Metrics
and sentiment-aggregate jobs remain full-universe reconciliation. Trading
still commits the ledger in FastAPI. See
[`docs/EVENT_DRIVEN_ARCHITECTURE.md`](./docs/EVENT_DRIVEN_ARCHITECTURE.md).

## Common commands

```bash
pnpm db:up                                   # local Postgres on 127.0.0.1:5434
pnpm events:up                               # KRaft Kafka + topic init (`--profile events`)
pnpm api:migrate                             # alembic upgrade head
pnpm api:dev                                 # uvicorn --reload on :8000
pnpm dev                                     # Next.js dev server on :3000 (or next free port)
pnpm lint && pnpm typecheck && pnpm build    # web + api lint, TS, build
uv --directory apps/api run pytest           # API tests (pytest -k <name> to focus)
pnpm e2e                                     # Playwright (needs built web + running API)
pnpm k8s:create && pnpm k8s:build && pnpm k8s:deploy && pnpm k8s:smoke
                                             # kind + Strimzi lab (needs Docker)
```

## Adding a feature end-to-end

The repo follows a strict one-file-per-resource pattern on both sides. For a
new resource, walk the chain in order:

1. `apps/api/src/stockviz/models/<resource>.py` — SQLModel table(s); import
   them in `models/__init__.py` so Alembic sees the metadata.
2. `uv --directory apps/api run alembic revision --autogenerate -m "..."` —
   review the generated file, then `alembic upgrade head`.
3. `apps/api/src/stockviz/services/<resource>/` — the business logic.
4. `apps/api/src/stockviz/routers/<resource>.py` — thin `/v1` router;
   register it in `main.py::create_app`. `UserIdDep` if authed,
   `@limiter.limit` if public (see the api guide's rate-limiting notes).
5. `apps/api/tests/test_<resource>_router.py` (+ service-level tests).
6. `apps/web/lib/api/<resource>.ts` — typed fetchers via `apiGet` (public)
   or `authedGet/authedPost` (per-user); re-export from `lib/api/index.ts`,
   shared types in `lib/api/types.ts`.
7. Page/components — `apps/web/app/<resource>/` (public) or
   `app/(authed)/<resource>/` (session required).
8. If the data needs periodic refresh, add a `scheduler.py` job **and** a
   matching `cli.py` subcommand (every job has a manual CLI twin).

## Current gaps

Use [`docs/KNOWN_LIMITATIONS.md`](./docs/KNOWN_LIMITATIONS.md) for verified
constraints and [`docs/ENGINEERING_ROADMAP.md`](./docs/ENGINEERING_ROADMAP.md)
for possible production hardening. Cross-check any proposal against the code
before starting it.

## Remotes

- **`origin`** → `https://github.com/itsmanudon/stock-viz-simulator.git` (the
  active fork; this is where all pushes go).
- **`upstream`** → `https://github.com/itsmanudon/StockViz.git` (the original
  copy-from repo; kept for reference only — do **not** push to it).

`git remote -v` should show both. If you ever need to sync something from the
original (you probably won't), `git fetch upstream` first, then cherry-pick.

## Branching workflow

```
main ← dev ← feat/* | fix/* | chore/*
```

**Hard rule:** cut every branch from `dev`. Open every PR against `dev`.
`main` receives **only** merges of `dev` — never merge a feature/fix/chore
branch, Cursor agent branch, or hotfix into `main` directly.

- **`main`** — release branch. Intended production hosts are Vercel (web) and
  Render (API + DB). `infra/render.yaml` has `autoDeploy: true`; whether a
  dashboard currently deploys on push is owner-controlled and **not** recorded
  in this repo. Promote with a `dev` → `main` merge (or PR). Do **not** open
  PRs against `main` except that promotion.
- **`dev`** — the integration branch. All feature/fix/chore PRs target `dev`.
  Kept green at all times; merged into `main` for each deployable release.
- **`feat/<name>`**, **`fix/<name>`**, **`chore/<name>`** — short-lived
  branches cut from `dev`. Open a PR against `dev` when ready; delete after
  merge. Use the prefix that best describes the work:
  - `feat/` — new user-facing functionality
  - `fix/` — bug fixes
  - `chore/` — tooling, deps, docs, CI, refactors with no user impact

- **`migration`** and **`v2`** — **deprecated.** Integration branches during
  the v2 rewrite (Phases 1–7); fast-forwarded into `main` when Phase 7
  shipped. Don't push to them or open PRs against them.

Tags:

- `v1.0.0` — pre-rewrite v1 site (recover the legacy source with `git checkout v1.0.0`).
- `v2.0.0` — the moment v1 and v2 coexisted, right before the v1 tree was
  deleted (`git checkout v2.0.0` to see both side-by-side).

The rewrite history is preserved in the Git log and release tags; it is not
current architecture guidance.

## Common gotchas (Windows dev)

- Postgres in Docker binds **5434**, not 5432, because the user has a native install on 5432.
  Use `127.0.0.1:5434` everywhere — see `infra/docker-compose.yml`.
- Use `127.0.0.1` not `localhost` in env defaults. Windows IPv6 lookups can bypass
  the dev container otherwise.
- The dev port 3000 is often held by another local service; Next silently bumps
  to the next free port (3001, 3005, ...). `AUTH_URL` is intentionally **unset**
  in `.env.example` so NextAuth derives the URL from the request host — dev
  works on any port. Only set `AUTH_URL` in production.

## Commits and PRs

**Keep these guides honest:** a PR that adds a router, page, model, scheduler
job, or env var — or changes auth/trading semantics — must update the relevant
`CLAUDE.md` (root, `apps/api/`, or `apps/web/`) in the same PR. These files
have drifted badly before (a whole auth mechanism was documented long after it
was replaced); the cheapest time to fix that is while the change is fresh.

When work closes a GitHub issue, reference it explicitly:

- **Commit messages** — add `Closes #<n>` (or `Fixes #<n>`) in the commit body.
- **PR descriptions** — list every closed issue in the body, e.g. `Closes #4, Closes #5`.

**Important:** GitHub only auto-closes issues when a PR merges into the **default
branch** (`main`). Because all our PRs target `dev`, `Closes #X` keywords in the
PR body will **not** trigger auto-close. You must close issues manually as soon as
the feature PR is opened:

```bash
gh issue comment <n> --repo itsmanudon/stock-viz-simulator --body "Implemented in PR #<pr>. Closes #<n>."
gh issue close <n> --repo itsmanudon/stock-viz-simulator
```

## Quality gates

`pnpm lint && pnpm typecheck && pnpm build && uv --directory apps/api run pytest` — all
of these run in CI on PRs, plus a full-stack **e2e job** (migrate + seed +
backfill against a real Postgres, start the API, build the web app, run
Playwright). Don't bypass with `--no-verify` etc.

## Auth bridge (web ↔ api)

The Next.js server mints a **short-lived HS256 JWT** (`{ sub: "<db user.id>" }`,
60 s expiry) signed with the shared `INTERNAL_API_TOKEN` secret and sends it as
`Authorization: Bearer <token>` on authenticated `/v1` calls. The browser never
sees the token — the client lives in `apps/web/lib/api/server.ts` (marked
`import "server-only"`, signs with `jose`) and FastAPI verifies it in
`apps/api/src/stockviz/auth.py::require_user_id` (`UserIdDep`).

This replaced the earlier `X-Internal-Token` + `X-User-Id` header bridge —
older docs/comments mentioning those headers are historical.

## Env vars that bite

Full lists live in `apps/web/.env.example` and `apps/api/.env.example`
(committed values are safe dev defaults). The ones that cause real breakage:

| Var                                                      | App(s)                       | What breaks / notes                                                                                                                                                                                                          |
| -------------------------------------------------------- | ---------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `INTERNAL_API_TOKEN`                                     | both — **must be identical** | signs/verifies the web→api JWT; mismatch = every authed `/v1` call 401s                                                                                                                                                      |
| `AUTH_SECRET`                                            | web                          | NextAuth session JWT signing                                                                                                                                                                                                 |
| `AUTH_TRUST_HOST=true`                                   | web                          | needed whenever you run a **production** build outside Vercel (CI e2e, local `next start`)                                                                                                                                   |
| `DATABASE_URL`                                           | both                         | web wants plain `postgres://` (node-postgres); the API rewrites `postgres://`→`postgresql+psycopg://` in `settings.py`, don't fight it                                                                                       |
| `ENABLE_SCHEDULER`                                       | api                          | off by default; Render sets `true` (in-process). Kubernetes API pods keep it `false` and run `python -m stockviz.workers.scheduler`                                                                                          |
| `RATELIMIT_ENABLED=0`                                    | api                          | disables the slowapi rate limiter (handy for tests/load scripts)                                                                                                                                                             |
| `ALPHA_VANTAGE_KEY`, `NEWSDATA_KEY`, `ANTHROPIC_API_KEY` | api                          | News (`NEWSDATA_KEY`) and sentiment (`ANTHROPIC_API_KEY`) **silently no-op** when blank. A blank `ALPHA_VANTAGE_KEY` only skips the Alpha Vantage **fallback**; the market-ingest worker still uses yfinance for daily OHLCV |
| `SENTIMENT_PROVIDER`                                     | api                          | `none` (default) \| `anthropic` \| `http`. Blank resolves to `anthropic` when `ANTHROPIC_API_KEY` is set. See [`docs/SENTIMENT.md`](./docs/SENTIMENT.md)                                                                     |
| `SENTIMENT_SERVICE_URL`, `SENTIMENT_SERVICE_TOKEN`       | api                          | only read when `SENTIMENT_PROVIDER=http` — the standalone scoring service                                                                                                                                                    |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`               | web                          | Google OAuth sign-in                                                                                                                                                                                                         |
| `NEXTAUTH_JWT_SECRET`                                    | api                          | **legacy** — still in `settings.py` but no longer read by the auth bridge                                                                                                                                                    |

## Sentry

Both apps init Sentry only when a DSN env var is present, so dev/CI builds
work fine without one. Env vars live in `apps/web/.env.example` and
`apps/api/.env.example`.

## Deploy targets

- Web → Vercel (`apps/web/vercel.json`)
- API + DB → Render (`infra/render.yaml`)
- kind / CI lab → [`docs/KUBERNETES.md`](./docs/KUBERNETES.md) (Kustomize +
  Strimzi). Not a production control plane.

Daily refresh on Render runs **in-process** via APScheduler
(`ENABLE_SCHEDULER=true`) inside the FastAPI service — there's no separate
cron service in the Blueprint because Render dropped the free cron tier.
Kubernetes runs the same jobs in a singleton scheduler Deployment. The
`stockviz` CLI subcommands re-run the same job logic manually. See
`docs/DEPLOYMENT.md` for how to re-add a cron service on a paid plan.
