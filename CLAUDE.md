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

Three long-lived branches:

- **`main`** — default branch, what Vercel + Render deploy from. Holds the
  shipped v2 codebase. Tagged `v2.0.0` at the moment v1 and v2 coexisted; the
  next commit deleted the v1 tree. Tag `v1.0.0` points at pre-rewrite v1.
- **`migration`** — integration branch where each v2 phase lands. Fast-forwarded
  into `main` once Phase 7 shipped.
- **`v2`** — active feature branch. Phase-by-phase work continues here.

Cycle: develop on `v2` → commit phase → checkout `migration` → `git merge v2 --no-ff` →
back to `v2` for the next phase. Use `--no-ff` so each phase reads as a single commit
on `migration`. See `memory/project_branching_workflow.md`.

To recover the legacy v1 source: `git checkout v2.0.0` (state where both
codebases coexisted) or `git checkout v1.0.0` (v1-only).

## Common gotchas (Windows dev)

- Postgres in Docker binds **5434**, not 5432, because the user has a native install on 5432.
  Use `127.0.0.1:5434` everywhere — see `infra/docker-compose.yml`.
- Use `127.0.0.1` not `localhost` in env defaults. Windows IPv6 lookups can bypass
  the dev container otherwise. See `memory/project_dev_environment_quirks.md`.
- The dev port 3000 is sometimes held by another local service (sprintserve); Next
  silently bumps to 3001 — that's why `.env.example` ships `AUTH_URL=http://127.0.0.1:3001`.

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
- API + DB + cron → Render (`infra/render.yaml`)

The Render `cron` service runs the same Docker image as the web service but
overrides the command to invoke `python -m stockviz.cli ingest ... && recommend`
as a nightly safety net even if the in-process scheduler misses.
