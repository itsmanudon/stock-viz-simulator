# StockViz Rewrite Plan

> **Historical.** Written before the v2 rewrite. All seven phases shipped.
> Do not treat the stack table, `packages/shared` layout, open questions, or
> “live URL anyone can sign up to” as current — the app is Next.js 16 +
> FastAPI, `packages/` was never created, and this repo does not publish a
> live URL. See [`README.md`](./README.md) and
> [`docs/RESUME_GAPS.md`](./docs/RESUME_GAPS.md) for what exists today.

Plan for rewriting the 1-year-old `stock-viz-simulator` (static HTML/CSS/JS + standalone Python scripts) into a modern full-stack product with live data, real auth, and a DB-backed paper-trading simulator.

## Goals

1. **Real product with real users** — not a portfolio piece. The rewrite must support live data, real accounts, persistent portfolios, and mobile-responsive UI.
2. **Operable codebase** — typed, linted, tested, deployable from CI, no hardcoded local paths.
3. **Live data** — replace static CSVs (last refreshed ~14 months ago) with a scheduled ingestion pipeline writing to Postgres.
4. **Component-driven frontend** — remove the duplicated headers/footers across 7 hand-written HTML files.
5. **Real auth + portfolios** — replace the UI-only login/signup with NextAuth-backed sessions and DB-backed portfolios.

## Current-state audit (what we are leaving behind)

- ~2,500 LOC: 1,200 lines HTML, 1,900 lines JS across 6 page-scoped files, ~500 lines Python.
- 7 standalone HTML pages each re-declaring the same nav/header/footer markup.
- 12 per-page CSS files, one per HTML page, with overlapping styles.
- 25 hardcoded tickers; data stored as static CSVs in `website/stock-data-csv-files/` and `website/news-data-csv-files/`.
- Python pipeline in `API/` and `StockProcessing/` writes CSVs to disk; does not power the live site.
- `main.py:70` hardcodes `D:\Github Repos\Sem-2-Project` — breaks for anyone else.
- README mentions SQLAlchemy / `Database/` module that does not exist in the tree.
- Login/signup pages exist but have no backend — pure UI.
- Mixed legacy and modern Python files (`__pycache__` committed, `temp_data_comp.json` and `temp.json` committed).

## Target architecture

### Stack

| Layer | Choice | Rationale |
|---|---|---|
| Frontend | Next.js 15 (App Router), TypeScript, Tailwind, shadcn/ui | Server components for fast first paint, owned components for theming, industry-standard. |
| Auth | NextAuth (Auth.js) v5 | Self-hosted, no vendor lock-in, supports OAuth + credentials. |
| Charts | `lightweight-charts` (TradingView) | Purpose-built for OHLCV + indicators; better than Chart.js for this domain. |
| Backend | FastAPI (Python 3.12) | Reuses existing `API/` + `StockProcessing/` work; great for data work. |
| ORM / migrations | SQLModel + Alembic | Type-safe, Pydantic-aligned, mature migrations. |
| DB | Postgres 16 | Local via docker-compose; managed in prod. |
| Ingestion | APScheduler inside FastAPI process | Simple; promote to RQ/Celery only if it outgrows in-process. |
| Data sources | Alpha Vantage (primary), yfinance (fallback), Newsdata.io | Already integrated; keep API keys server-side only. |
| Package managers | pnpm (JS), uv (Python) | Fast, modern, deterministic. |
| Lint / format | biome (JS/TS), ruff (Python), prettier (markdown/json) | One-tool linters; fast. |
| CI | GitHub Actions | Lint + type-check + test on PR; deploy on merge. |
| Hosting | Vercel (web), Render (api + db + cron) | Free tiers cover hobby usage; one-click deploys from git. |
| Monitoring | Sentry (free tier) | Errors on both web and api. |

### Repo layout

```
stock-viz-simulator/
├── apps/
│   ├── web/                    # Next.js
│   │   ├── app/
│   │   ├── components/         # shadcn/ui + custom
│   │   ├── lib/                # api client, auth helpers
│   │   └── styles/
│   └── api/                    # FastAPI
│       ├── src/stockviz/
│       │   ├── main.py
│       │   ├── routers/        # symbols, bars, news, trades, portfolio
│       │   ├── models/         # SQLModel
│       │   ├── services/
│       │   │   ├── ingest/     # ported from API/ + StockProcessing/
│       │   │   └── recommend/  # ported from scripts/algo.py
│       │   ├── scheduler.py
│       │   └── settings.py
│       ├── migrations/         # Alembic
│       └── tests/
├── packages/
│   └── shared/                 # TS types generated from FastAPI OpenAPI
├── infra/
│   ├── docker-compose.yml
│   └── render.yaml
├── .github/workflows/
└── README.md
```

### Data model

```
users              (id, email, name, image, created_at)               -- NextAuth-managed
accounts           (NextAuth)
sessions           (NextAuth)

symbols            (ticker PK, name, sector, exchange, is_active)
price_bars         (symbol_fk, ts, open, high, low, close, volume, interval)   -- PK(symbol, ts, interval)
news_articles      (id, symbol_fk, title, url, source, published_at, summary, image_url)

portfolios         (id, user_fk, name, cash_balance, created_at)
positions          (id, portfolio_fk, symbol_fk, quantity, avg_cost)
trades             (id, portfolio_fk, symbol_fk, side, quantity, price, ts)
watchlists         (id, user_fk, name)
watchlist_items    (watchlist_fk, symbol_fk)
recommendations    (symbol_fk, score, rationale, computed_at)
```

### API surface (v1)

Public:
- `GET /v1/symbols` — list, filterable by sector/exchange
- `GET /v1/symbols/{ticker}` — metadata + latest quote
- `GET /v1/symbols/{ticker}/bars?interval=1d&from=&to=`
- `GET /v1/symbols/{ticker}/news?limit=`
- `GET /v1/quotes?tickers=AAPL,MSFT,...` — batch latest
- `GET /v1/recommendations`

Authenticated (NextAuth JWT verified server-side):
- `GET /v1/portfolio` — default portfolio + positions + cash
- `POST /v1/trades` — `{ticker, side, quantity}` → fills at latest cached close
- `GET /v1/trades` — history
- `GET /v1/watchlists`, `POST /v1/watchlists`, `POST /v1/watchlists/{id}/items`

## Phased roadmap

Each phase ends with a deployable, demoable state.

### Phase 1 — Scaffold & infra (target: 1–2 days)
- New branch `v2` off `main`.
- Initialize pnpm workspace, Next.js app, FastAPI app, shared package.
- docker-compose with Postgres + adminer.
- biome, ruff, prettier, pre-commit hooks.
- `.env.example` for both apps; secrets out of git.
- GitHub Actions: lint + type-check on PR.
- Deliverable: `pnpm dev` boots a hello-world Next.js + FastAPI talking to local Postgres.

### Phase 2 — Backend foundation (target: 3–4 days)
- SQLModel models + Alembic baseline migration.
- Port `API/stock_data.py`, `API/newsdata.py`, `StockProcessing/data_processor.py`, `StockProcessing/newsdata_processor.py` into `services/ingest/` — clean classes, no CSV writes, write straight to DB.
- APScheduler jobs: daily EOD pull for all symbols, hourly for top 25, news every 4h.
- One-time backfill from existing CSVs to seed DB (don't re-fetch what we already have).
- Endpoints: `/symbols`, `/symbols/{ticker}`, `/bars`, `/news`, `/quotes`.
- Tests for ingest parsers (use real Alpha Vantage response fixtures).
- Deliverable: API serving real data from Postgres; OpenAPI docs at `/docs`.

### Phase 3 — Frontend foundation (target: 2–3 days)
- App Router layout: shared header (logo, nav, search, account menu), footer, dark/gold theme matching existing palette.
- shadcn/ui set up; install components as needed.
- NextAuth v5 with Google OAuth + credentials. Sessions in Postgres (shared DB).
- API client in `apps/web/lib/api.ts` generated from FastAPI's OpenAPI schema.
- Landing page `/` with hero, top movers, market overview pulling from API.
- Deliverable: working homepage with login, header/footer shared across all pages.

### Phase 4 — Markets + ticker detail (target: 3–4 days)
- `/markets` — sortable/filterable table of all symbols with sparklines.
- `/stocks/[ticker]` — OHLCV candlestick via `lightweight-charts`, volume pane, indicator toggles (SMA 20/50/200, EMA, RSI, MACD), timeframe selector, related news.
- Indicators computed server-side in `services/indicators/` (one function per indicator, well-tested).
- Deliverable: replaces `markets.html` + per-stock view.

### Phase 5 — Compare, news, recommendations (target: 2–3 days)
- `/compare?tickers=AAPL,MSFT,...` — normalized line chart, return %, sector breakdown.
- `/news` — paginated news feed from DB.
- `/recommendations` — port `scripts/algo.py` to `services/recommend/`, expose endpoint, render cards with rationale.
- Deliverable: replaces `compare.html`, `news.html`, `recommendation.html`.

### Phase 6 — Trade simulator (target: 3–4 days)
- `/trade` — order ticket (market buy/sell), validates cash + position.
- `/portfolio` — positions table, current value, unrealized P&L, history chart.
- `/trades` — full trade history.
- All persisted server-side per user.
- Deliverable: real working paper-trading product.

### Phase 7 — Deploy & polish (target: 1–2 days)
- Vercel project for `apps/web`; Render service + Postgres + cron for `apps/api`.
- Sentry on both.
- New README with screenshots, architecture diagram, setup instructions.
- Domain (optional).
- Deliverable: live URL anyone can sign up to.

**Total estimate:** ~15–22 focused days, or 6–8 weeks part-time.

## Decisions captured

- **Goal:** real product with real users.
- **Stack:** Next.js + FastAPI + Postgres.
- **Data:** live API (Alpha Vantage + yfinance) cached in DB; not on-request.
- **Auth:** NextAuth v5.
- **UI library:** shadcn/ui + Tailwind.
- **Repo strategy:** rewrite on a `v2` branch in this repo; merge to `main` when Phase 7 ships.

## Open questions to resolve before Phase 2

1. **Primary data source** — Alpha Vantage's free tier is 25 req/day. Is that enough, or do we go with yfinance as primary (no key, unofficial) and Alpha Vantage as fallback?
2. **Intraday data?** — EOD only is much easier. Intraday adds rate-limit and storage pressure.
3. **OAuth providers** — Google only, or also GitHub/email-password?
4. **Symbol universe** — keep the existing 25, or expand (S&P 500 = 500 rows × ~5 years × 252 bars ≈ 630k rows, trivial for Postgres)?
5. **Mobile-first or desktop-first?** — affects layout decisions in Phase 3.

## What gets deleted from `main` (at Phase 7 merge)

- `API/` (ported to `apps/api/src/stockviz/services/ingest/`)
- `StockProcessing/` (ported into same module)
- `scripts/algo.py` (ported to `services/recommend/`)
- `website/` (replaced entirely by `apps/web/`)
- `index.html`, `main.py`, `companies.json` (replaced by DB seed)
- `website/stock-data-csv-files/`, `website/news-data-csv-files/` (replaced by DB)
- All `__pycache__/` and `temp*.json` (should not have been committed)

## What gets kept

- `LICENSE`
- Git history (we're branching, not wiping)
- Existing 25 tickers — re-seeded from `companies.json` into the `symbols` table during Phase 2 backfill.
