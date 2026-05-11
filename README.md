# StockViz

Live market data, technical indicators, and a paper-trading simulator.

> **v2 rewrite in progress** on the `v2` branch. The original static-HTML site is tagged [`v1.0.0`](../../tree/v1.0.0). See [`REWRITE_PLAN.md`](./REWRITE_PLAN.md) for the full rewrite roadmap.

## Stack

- **Web:** Next.js 16, React 19, TypeScript, Tailwind v4, shadcn/ui — `apps/web`
- **API:** FastAPI, SQLModel, Alembic, APScheduler — `apps/api`
- **DB:** Postgres 16 (Docker) — `infra/docker-compose.yml`
- **Auth:** NextAuth v5 _(added in Phase 3)_
- **Charts:** lightweight-charts _(added in Phase 4)_

## Prerequisites

- Node.js 22+ ([nvm](https://github.com/coreybutler/nvm-windows) recommended; see `.nvmrc`)
- pnpm 11+ (`npm install -g pnpm`)
- Python 3.12+ via [uv](https://docs.astral.sh/uv/) (`winget install --id=astral-sh.uv`)
- Docker Desktop

## Dev setup

```powershell
# install all JS deps (one-time)
pnpm install

# sync Python deps (one-time)
uv --directory apps/api sync

# start Postgres + Adminer (background)
pnpm db:up

# in two terminals:
pnpm api:dev    # FastAPI on http://127.0.0.1:8000
pnpm dev:web    # Next.js on http://localhost:3000
```

Open http://localhost:3000. The homepage shows the backend health (`status · api version · db up/down`).

OpenAPI docs are at http://127.0.0.1:8000/docs. Adminer is at http://localhost:8080 (server: `postgres`, user/pass/db: `stockviz`/`stockviz_dev`/`stockviz`).

### Port assignments

| Service        | Port |
| -------------- | ---- |
| Web (Next.js)  | 3000 |
| API (FastAPI)  | 8000 |
| Postgres       | 5434 |
| Adminer        | 8080 |

Postgres is on **5434** (not 5432) to avoid conflicts with a native Postgres install or other Docker projects. Adjust `apps/api/.env` if you need a different host port.

## Environment

Copy `.env.example` to `.env.local` (web) and `.env` (api), then fill in any secrets:

```powershell
Copy-Item apps/web/.env.example apps/web/.env.local
Copy-Item apps/api/.env.example apps/api/.env
```

Required keys for full functionality (added per phase):

- `ALPHA_VANTAGE_KEY` (Phase 2 — get one at https://www.alphavantage.co/support/#api-key)
- `NEWSDATA_KEY` (Phase 2 — get one at https://newsdata.io/)
- `NEXTAUTH_SECRET`, OAuth client IDs (Phase 3)

## Repo layout

```
apps/
  web/          Next.js frontend
  api/          FastAPI backend
packages/       Shared TypeScript packages
infra/          docker-compose and deploy configs
.github/        CI workflows
REWRITE_PLAN.md Detailed rewrite roadmap
```

## Quality

```powershell
pnpm lint        # biome (web) + ruff (api)
pnpm typecheck   # tsc + pyright
uv --directory apps/api run pytest
```

## License

MIT — see [LICENSE](./LICENSE).
