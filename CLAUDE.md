# StockViz — agent guide

Two-app pnpm + uv monorepo. See [`REWRITE_PLAN.md`](./REWRITE_PLAN.md) for the
full rewrite history and [`README.md`](./README.md) for setup/deploy.

## Layout you'll actually touch

```
apps/web/    Next.js 16 (App Router, React 19, TS, Tailwind v4, NextAuth v5)
apps/api/    FastAPI + SQLModel + Alembic + APScheduler
infra/       docker-compose (local Postgres) + render.yaml (prod blueprint)
.github/workflows/ci.yml   lint + typecheck + test on PR
```

Each app has its own `CLAUDE.md` with deeper notes. Skim those before editing.

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

- **`main`** — production branch. Vercel and Render auto-deploy from it.
  Only receives merges from `dev` when a milestone is ready to ship.
  Do **not** open feature PRs directly against `main`.
- **`dev`** — the integration branch. All feature/fix/chore PRs target `dev`.
  Kept green at all times; merged into `main` for each deployable release.
- **`feat/<name>`**, **`fix/<name>`**, **`chore/<name>`** — short-lived
  branches cut from `dev`. Open a PR against `dev` when ready; delete after
  merge. Use the prefix that best describes the work:
  - `feat/` — new user-facing functionality
  - `fix/` — bug fixes
  - `chore/` — tooling, deps, docs, CI, refactors with no user impact

- **`migration`** — **deprecated.** Was the integration branch during the v2
  rewrite (Phase 1-7). Fast-forwarded into `main` once Phase 7 shipped; do
  **not** push to it any more.
- **`v2`** — also **deprecated** for the same reason. Don't open new PRs
  against `v2` or `migration`.

Tags:

- `v1.0.0` — pre-rewrite v1 site (recover the legacy source with `git checkout v1.0.0`).
- `v2.0.0` — the moment v1 and v2 coexisted, right before the v1 tree was
  deleted (`git checkout v2.0.0` to see both side-by-side).

The phase-by-phase rewrite history is preserved as merge commits in `main`'s
log; see `REWRITE_PLAN.md` and `memory/project_branching_workflow.md` for
background.

## Common gotchas (Windows dev)

- Postgres in Docker binds **5434**, not 5432, because the user has a native install on 5432.
  Use `127.0.0.1:5434` everywhere — see `infra/docker-compose.yml`.
- Use `127.0.0.1` not `localhost` in env defaults. Windows IPv6 lookups can bypass
  the dev container otherwise. See `memory/project_dev_environment_quirks.md`.
- The dev port 3000 is often held by another local service; Next silently bumps
  to the next free port (3001, 3005, ...). `AUTH_URL` is intentionally **unset**
  in `.env.example` so NextAuth derives the URL from the request host — dev
  works on any port. Only set `AUTH_URL` in production.

## Commits and PRs

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
of these run in CI on PRs. Don't bypass with `--no-verify` etc.

## Auth bridge (web ↔ api)

The Next.js server attaches `X-Internal-Token` (matching `INTERNAL_API_TOKEN`)
plus `X-User-Id` (the DB user.id) when calling authenticated `/v1` endpoints.
The browser never sees these headers — the API client lives in
`apps/web/lib/api/server.ts` (marked `import "server-only"`) and FastAPI
verifies them in `apps/api/src/stockviz/auth.py::require_user_id`.

This is the Phase 6 bridge; a real NextAuth JWT verification path is the
documented upgrade target (see `auth.py` docstring).

## Sentry (Phase 7)

Both apps init Sentry only when a DSN env var is present, so dev/CI builds
work fine without one. Env vars live in `apps/web/.env.example` and
`apps/api/.env.example`.

## Deploy targets

- Web → Vercel (`apps/web/vercel.json`)
- API + DB → Render (`infra/render.yaml`)

Daily refresh runs **in-process** via APScheduler (`ENABLE_SCHEDULER=true`)
inside the FastAPI service — there's no separate cron service in the
Blueprint because Render dropped the free cron tier. See
`docs/DEPLOYMENT.md` for how to re-add one on a paid plan.
