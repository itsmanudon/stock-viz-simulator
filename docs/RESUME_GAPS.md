# StockViz — resume-ready gaps

Checked against the `dev` tree after `dev` was merged into `main` (commit
`a66d278`). This is a recruiter-honest inventory: what the code actually
does, what the docs still claim, and what is unfinished. It is not a
changelog of the v2 rewrite — that history is in [`REWRITE_PLAN.md`](../REWRITE_PLAN.md)
(historical) and [`IDEAS.md`](./IDEAS.md) (shipped list + remaining backlog).

No public live URL, screenshots, or usage metrics are claimed here because
none are in the repository.

---

## What actually ships

A Next.js 16 + FastAPI + Postgres paper-trading app. Local clone-and-run is
documented in [`SETUP.md`](./SETUP.md). Intended hosts are Vercel (web) and
Render (API + Postgres); dashboard auto-deploys are currently **off**, so
merging to `main` does not ship by itself.

### Pages (verified under `apps/web/app`)

| Route | What it is |
| --- | --- |
| `/` | Landing |
| `/markets` | Symbol table + sparklines (one-call `/v1/markets/summary`) |
| `/stocks/[ticker]` | OHLCV chart, SMA/EMA/RSI/MACD, news, comments, SSE badge |
| `/compare` | Normalized multi-ticker chart |
| `/news` | Paginated news |
| `/recommendations` | Daily scored candidates |
| `/screener` | Filterable universe |
| `/backtest` | Historical strategy runner |
| `/leaderboard` | Public NAV ranking |
| `/login`, `/signup` | Credentials + Google OAuth button |
| `/portfolio`, `/trade`, `/trades`, `/orders`, `/watchlist`, `/settings` | Authed paper-trading |

Alerts are a header bell (`/api/alerts`), not a standalone page. Options
trading is on `/trade` + `/portfolio`, not a dedicated `/options` route.

### Backend (verified in `apps/api`)

Routers registered from `main.py`: health, symbols (including search), bars,
markets summary, quotes, indicators, news, recommendations, trading, orders,
options, watchlist, alerts, leaderboard, screener, sentiment, comments,
backtest, SSE stream.

Auth for `/v1` paper-trading endpoints is a **60-second HS256 JWT** minted by
the Next.js server with `INTERNAL_API_TOKEN` and sent as
`Authorization: Bearer …`. The old `X-Internal-Token` + `X-User-Id` bridge
is gone.

Daily work runs **in-process** via APScheduler when `ENABLE_SCHEDULER=true`
(prices, FX, metrics, sentiment aggregate, recommendations, snapshots,
pending-order settlement, dividends, option expiry, news, hourly top-movers
+ alert evaluation). Jobs take a Postgres advisory lock so two instances
cannot double-fill.

### Also in the code, not just the original README list

Watchlists, limit/stop/take-profit orders, long-only options (NAV includes
option mark-to-model), dividends, multi-currency FX, portfolio analytics and
equity curve, realized P&L on sell fills, news-sentiment provider abstraction
(`none` / `anthropic` / `http`), a 7th recommendation vote from trailing
sentiment, symbol search **API**, SSE quotes that are a **Gaussian random
walk off the last close** (not a live exchange feed).

---

## Shipped vs claimed

| Claim | Reality |
| --- | --- |
| README “What it does” | Undersells: omits watchlist, orders, options, screener, backtest, leaderboard, alerts, sentiment, OAuth, FX/dividends. |
| README / SETUP “CI on PRs to `main`; work off `main`” | PRs target **`dev`**. CI runs on push/PR to **`dev` and `main`**. |
| README architecture: Bearer `INTERNAL_API_TOKEN` + `X-User-Id` | JWT signed *with* that secret; **no `X-User-Id` header**. |
| DEPLOYMENT: `AUTH_SECRET` must equal `NEXTAUTH_JWT_SECRET`; API verifies that pair | Wrong. NextAuth signs sessions with `AUTH_SECRET`. The API bridge verifies with **`INTERNAL_API_TOKEN`**. `NEXTAUTH_JWT_SECRET` is unused leftover. |
| DEPLOYMENT: “push to `main` → both rebuild automatically” | `infra/render.yaml` still has `autoDeploy: true`, but the owner has dashboard auto-deploys **disabled**. This PR does not flip that. |
| DEPLOYMENT daily jobs (four bullets) | Scheduler has **eleven** jobs (see `scheduler.py` / `apps/api/CLAUDE.md`). |
| `/recommendations` copy “6-vote” / `{score}/6` | Engine is **7 votes** (`MAX_SCORE = 7`); the seventh is news sentiment. |
| REWRITE_PLAN Next.js 15, `packages/shared`, “live URL anyone can sign up to” | Historical plan. App is Next.js 16; `packages/` was never created; no live URL is in this repo. |
| `CODEBASE_REVIEW.md` “Status: addressed” | The expensive correctness/security/CI items largely **did** land. Product-gap section 7 and several UI wires did not. Treat the file as the audit record, not a guarantee that every bullet is done. |
| `apps/web/.env.example` → `/memory/project_dev_environment_quirks.md` | That path does not exist in the repo. |
| Workspace `packages/*` | `pnpm-workspace.yaml` listed it; no `packages/` directory. |
| Vitest coverage in CI | `pnpm test:coverage` required `@vitest/coverage-v8`, which was not a dependency — the web unit-test CI step could not succeed. |
| Dependabot | Was added after the review, then **disabled** (this PR deletes `.github/dependabot.yml`). Advisory scanning in CI remains. |

---

## Leftover v1

The live v1 tree (`website/`, `API/`, `StockProcessing/`, root `index.html`)
is gone. Recover it with `git checkout v1.0.0`.

Still in the repo:

- `apps/api/seed-data/stock-data-csv-files/` — **used** by `stockviz.cli backfill`.
- `apps/api/seed-data/companies.json` — **used** by seed.
- `apps/api/seed-data/news-data-csv-files/` — **unused**. No Python path
  reads them. Kept rather than deleted; a news CSV backfill was never
  ported.
- `.idea/Sem-2-Project.*` was still tracked despite `.gitignore`. Removed
  from git in the polish commit.

---

## Clone-and-run holes (as found)

What works if you follow [`SETUP.md`](./SETUP.md): Docker Postgres on
`:5434`, migrate, `seed`, price `backfill`, two dev servers. Ingest keys
are optional; jobs no-op when blank.

What was broken or misleading:

1. **Web CI unit tests** — `test:coverage` without `@vitest/coverage-v8`.
2. **Auth docs** (README, DEPLOYMENT, both `.env.example`) described the
   wrong header contract.
3. **Google OAuth button always renders.** Without `GOOGLE_CLIENT_ID` /
   `GOOGLE_CLIENT_SECRET`, “Continue with Google” fails at runtime.
   Credentials signup still works.
4. **`NEXTAUTH_JWT_SECRET`** was in the production fail-closed list even
   though the auth bridge does not read it — a new Render boot could refuse
   to start for an unused secret.
5. Seed without `backfill` yields an empty markets table (symbols exist,
   no bars). SETUP already says to run both; easy to skip.
6. Playwright e2e needs a **production** web build (`pnpm start`) plus the
   API and `AUTH_TRUST_HOST=true`. `pnpm e2e` against `pnpm dev:web` is not
   the CI path.

---

## Tests (counts at audit time)

| Suite | What is there |
| --- | --- |
| pytest | 303 tests / 31 files. Strong on trading, options, orders, sentiment, screener, health. |
| Vitest | 3 readable files (~30 cases): CSV export, markets table helpers, login rate-limit. A `redirect.test.ts` existed but was stored with a raw NUL byte, so editors and `rg` treated it as binary. Rewritten as text in this PR; `searchSymbols` empty-query coverage added. |
| Playwright | 3 specs / 6 tests: markets, auth signup, one buy trade. No e2e for options, orders, backtest, screener, leaderboard. |

CI also builds the API Docker image, runs `alembic check`, `uv lock --check`,
and dependency audits. There is **no coverage fail-under gate**.

---

## Ranked next work

Ordered by how much it would change what a recruiter or a new clone actually
sees. Not a commitment to build these in this PR.

1. **Close the open Dependabot PRs in the GitHub UI** (this token cannot).
   Version updates will stop after this file deletion reaches `main`.
2. **Decide auto-deploy.** `render.yaml` still says `autoDeploy: true`;
   dashboards are off. Pick one story and leave the other as a comment.
   Do not silently turn production deploys on.
3. **Wire APIs that already exist:** header typeahead (`searchSymbols`),
   screener sentiment filters, ticker-page sentiment series overlay
   (`GET /v1/symbols/{ticker}/sentiment`). None of these need a new backend.
4. **Hide Google OAuth when env keys are empty** so local signup is not a
   trap.
5. **Auth product:** password reset, email verification, change-password,
   brute-force lockout on the Next.js actions. Credentials-only is fine for
   a demo; it is not fine if real people keep accounts.
6. **Trading product leftovers:** pending-order cash reservation (two large
   buys can both sit pending); aggregated realized P&L on `/portfolio`;
   options IV disclosed as 30-day historical vol in the UI; cash
   deposits/withdrawals (would force time-weighted returns).
7. **Alerts:** email/push, weekend evaluation, one-shot vs repeat. In-app
   bell only, hourly on weekdays 10:00–16:00 ET (bundled into
   `hourly_top_movers`).
8. **Sentiment track** (`IDEAS.md`): `sentiment_threshold` backtest
   strategy; `alert_type: sentiment`. Provider + `news_sentiment` table
   already exist.
9. **Ops:** Redis (or similar) for the rate limiter if you ever run more
   than one API instance; coverage gates; `CONTRIBUTING.md` / issue
   templates. `CODEOWNERS` and a PR template already exist.

---

## What this polish PR changed (and did not)

Changed: Dependabot config removed; docs aligned with the JWT bridge and
`dev` workflow; recommendations UI/CLI say 7 votes; Vitest coverage
provider installed; `redirect.test.ts` rewritten without a raw NUL;
`searchSymbols` empty-query test and Settings fail-closed tests added;
unused `NEXTAUTH_JWT_SECRET` dropped from the production fail-closed list
(field kept); `.idea/` untracked.

Not changed: no new product features; `render.yaml` `autoDeploy` left as-is;
no secrets committed; Dependabot Alerts left on; unused news CSVs left on
disk and documented above.
