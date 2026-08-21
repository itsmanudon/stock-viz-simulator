# StockViz — codebase review: gaps & improvements

Reviewed at commit `c4ecbb8` (main, post-Phase-7 + options/backtesting/leaderboard).
Scope: `apps/api` (FastAPI/SQLModel, ~12.4k LoC Python), `apps/web` (Next.js 16,
~8k LoC TS), `infra/`, `.github/`.

The codebase is in genuinely good shape — clean layering (routers → services →
models), Decimal money math, docstrings that explain *why*, 228 API tests, and
a real e2e suite. The findings below are the things that would bite in
production or block the next phase of work, ordered by how much they'd hurt.

---

## 1. Correctness — financial integrity

These are places where the ledger produces a wrong number. For a trading
simulator, these are the highest-value fixes: everything else is cosmetic if
the P&L is wrong.

### 1.1 Options positions are invisible to NAV, analytics, and the leaderboard 🔴

`services/trading/portfolio.py::compute_portfolio` reads only `Position`
(equities). `OptionsPosition` appears nowhere in `portfolio.py`,
`snapshots.py`, or `analytics.py`.

Consequence: opening an option debits cash (`open_option`), so NAV drops by the
premium and **never records the offsetting asset**. A user who buys $10k of
calls that double in value shows a $10k NAV loss until expiry. Daily snapshots
inherit the error, so `/portfolio/history`, Sharpe, max drawdown and the public
leaderboard are all wrong for anyone who touches options.

**Fix:** add an `options_market_value` leg to `compute_portfolio`, valuing each
open position with `value_option() * quantity * CONTRACT_MULTIPLIER`, and
include it in `total_value`. Extend `PortfolioValuation` with an
`option_positions` list so the UI can show it too.

### 1.2 Pending-order settlement ignores FX 🔴

`execute_trade` correctly converts native cost → USD via `latest_rate()` before
touching `cash_balance`. `services/trading/orders.py::_fill_order` does not —
it computes `cost = close * quantity` and debits that straight from the USD
cash bucket. A limit order on a JPY-denominated symbol debits yen as if they
were dollars.

**Fix:** extract the cash/position mutation from `execute_trade` into a shared
`_apply_fill(session, portfolio, ...)` helper and have both paths call it. That
also removes the duplicated `_latest_close` / `_get_or_create_position` /
weighted-average-cost logic currently copy-pasted between the two modules.

### 1.3 Dividend crediting ignores FX 🟠

Same class of bug: `credit_due_dividends` does
`portfolio.cash_balance += pos.quantity * div.amount` with no conversion. A
GBP dividend is credited as USD.

### 1.4 Pending orders don't reserve cash 🟠

Two pending buy orders for $80k each against a $100k balance both sit in the
table. At settlement the first fills and the second is silently **cancelled**
(`_fill_order` catches `InsufficientCash` and flips the order to `CANCELLED`).
Users get no explanation. Either reserve cash at order-creation time, or
surface a `cancel_reason` column so the orders page can say why.

### 1.5 Order settlement can fill against a stale close 🟠

`pending_orders_settlement` runs at 16:45 ET; `daily_price_refresh` at 16:30.
If the refresh fails or runs long, `_latest_close` returns *yesterday's* bar
and orders fill at a stale price with no guard. Settlement should assert the
bar's `ts` is today's session and skip (not cancel) otherwise. The two jobs
also have no dependency ordering — chaining them into one job, or using an
APScheduler listener, would make the sequencing explicit.

### 1.6 Backtest engine has look-ahead bias and zero costs 🟠

`run_backtest` computes a signal from bar *i*'s close and fills at bar *i*'s
close. You cannot know RSI(14) at the close until the close has printed, so the
fill should happen at bar *i+1*'s open. There is also no commission, no
slippage, and no bid/ask — results are systematically optimistic.

Also: `_sharpe` hardcodes risk-free = 0 while `compute_sharpe` in
`analytics.py` defaults to 0.05, so the same portfolio scores differently
depending on which surface renders it.

**Fix:** shift fills by one bar, add `commission_bps` / `slippage_bps` to
`BacktestIn` (default 0 keeps existing tests green), share the risk-free
constant, and add a **buy-and-hold benchmark** to `BacktestSummary` — without
it a user can't tell whether a strategy beat doing nothing, which is the
single most useful output a backtester can give.

### 1.7 Snapshot baseline is the first *snapshot*, not account opening

`compute_total_return_pct(navs)` and the leaderboard both use `navs[0]`. A
portfolio only gets its first snapshot after `ensure_default_portfolio` has run
*and* the 17:15 job has fired — any P&L before that is invisible, and the
leaderboard starts everyone's clock at a different point. Seed a snapshot at
portfolio creation with `DEFAULT_STARTING_CASH`.

---

## 2. Security

### 2.1 Dev secrets are silent production defaults 🔴

```python
# settings.py
nextauth_jwt_secret: str = "dev-secret-change-me"
internal_api_token: str = "dev-internal-token-change-me"
```
```ts
// lib/api/server.ts
const INTERNAL_TOKEN = process.env.INTERNAL_API_TOKEN ?? "dev-internal-token-change-me";
```

`render.yaml` marks `INTERNAL_API_TOKEN` as `sync: false`, meaning it must be
set by hand after the first deploy. If anyone forgets, the API happily verifies
JWTs signed with a secret that is published in this repo — and since
`require_user_id` trusts `sub` as the user id, an attacker can mint a token for
**any** user and read/modify their portfolio.

**Fix:** fail fast at startup. Add a `model_validator` on `Settings` that raises
when `environment == "production"` and any secret still equals its dev default.
Do the same on the web side (throw at module load rather than falling back to
the literal).

### 2.2 The SSE stream can exhaust the DB connection pool 🔴

`routers/stream.py::stream_quotes` takes `session: SessionDep` (a `yield`
dependency) and returns a `StreamingResponse` whose generator loops **forever**
with no max duration. FastAPI holds `yield` dependencies open for the life of
the response, so every open SSE connection pins one Postgres connection.
`create_engine` uses SQLAlchemy defaults (pool 5 + overflow 10), so roughly 15
concurrent viewers of a stock page deadlock the entire API.

The endpoint is also unauthenticated and uncapped.

**Fix:** read the initial close and close the session *before* returning the
stream (fetch it in a `with Session(engine)` block rather than via the
dependency), add a hard `MAX_STREAM_SECONDS` (~15 min), and rate-limit
connections per IP.

### 2.3 Rate limiting is effectively a single global bucket 🟠

`limiter.py` keys on `get_remote_address()`, which reads `request.client.host`.
Uvicorn is started without `--proxy-headers`, so behind Render's load balancer
every request appears to come from the proxy. All users share one 60/minute
bucket.

It compounds with §3.1: one `/markets` render issues 34 API calls, so **two
page loads per minute exhausts the limit for every user on the platform**.

**Fix:** add `--proxy-headers --forwarded-allow-ips="*"` to the Dockerfile CMD
and key the limiter on the authenticated user id where available, falling back
to `X-Forwarded-For`. For multi-instance correctness this needs a shared store
(Redis) rather than slowapi's in-process default.

### 2.4 No brute-force protection on login/signup 🟠

`loginAction` runs `bcrypt.compare` with no attempt counter, no lockout, no
CAPTCHA, and no per-IP throttle. The API has slowapi; the Next.js server
actions have nothing. Add a rate limit (Upstash/Redis, or a `login_attempts`
table) keyed on email + IP.

Related: `signupAction` does check-then-insert (`findUserByEmail`, then
`createUser`) — two concurrent signups race past the check and the second hits
the unique constraint as an unhandled 500 instead of "email already
registered". Catch the Postgres `23505` and return the friendly error.

### 2.5 Missing auth-lifecycle features

No email verification, no password reset, no session revocation, no
"change password" in `/settings`. For a paper-trading app with a public
leaderboard, password reset is the one users will actually ask for.

### 2.6 Container runs as root 🟡

`apps/api/Dockerfile` never sets `USER`. Add a non-root user in the runtime
stage. Also, `CMD` runs `alembic upgrade head` on every boot — safe at one
instance, a race the moment you scale to two.

### 2.7 `/health` always returns 200 🟡

`healthCheckPath: /health` in `render.yaml` — but the handler returns 200 with
`status: "degraded"` when the DB is down, so Render never restarts a broken
instance. Return 503 when `database == "down"`.

---

## 3. Performance & scale

### 3.1 `/markets` fans out to 34 backend requests per render 🔴

`app/markets/page.tsx` calls `listSymbols()` twice (once filtered, once for the
sector list) then `getBars()` once per symbol — 32 symbols today, and it grows
linearly with the universe. Every call is `cache: "no-store"`.

**Fix:** add `GET /v1/bars/batch?tickers=…&limit=30` (or a `/v1/markets/summary`
endpoint that returns ticker, name, sector, last close, change %, and the
sparkline series in one shot). Derive the sector list from the single symbols
response instead of a second fetch.

### 3.2 N+1 query patterns throughout the API 🟠

| Location | Pattern |
|---|---|
| `portfolio.py::_latest_close_map` | one query per ticker in a Python loop |
| `leaderboard.py::_build_leaderboard` | full snapshot history per public user |
| `trading.py::list_trades` | `session.get(Symbol, …)` per trade row |
| `trading.py::get_portfolio_analytics` | `session.get(Symbol, …)` per position |
| `screener.py::screen_symbols` | 260 bars per symbol, RSI recomputed per request |
| `comments.py::create_comment` | `len(list(select(...)))` to count — loads rows to count them |

The latest-close-per-ticker case is the worst offender because it's on the hot
path for every portfolio read. A single `DISTINCT ON (ticker)` query (or a
window function) replaces the whole loop. The comment rate-limit count should
be `select(func.count())`.

### 3.3 The screener has no cache and no result cap 🟠

Every request re-reads ~8,300 bar rows and recomputes RSI for the entire
universe. A materialized `symbol_metrics` table (ticker, last_close, rsi_14,
momentum_20d, high_52w, low_52w, computed_at) refreshed by the existing 17:00
job turns the screener into one indexed `SELECT … WHERE`, and gives the
recommendations engine and markets page the same numbers for free.

### 3.4 In-process state assumes exactly one instance 🟠

The leaderboard's module-level `_cache`/`_cache_ts` and the APScheduler
`BackgroundScheduler` both assume a single process. The cache-invalidation on
`PATCH /profile` only clears the local copy. On two instances, scheduled jobs
run **twice** — dividends are protected by the `portfolio_dividends` unique
constraint, but order settlement and option expiry are not, so a double-fire
double-fills orders.

**Fix (cheap):** an advisory-lock guard (`pg_try_advisory_lock`) around each
job body. **Fix (proper):** APScheduler with `SQLAlchemyJobStore`, or promote
the scheduler to a separate worker service.

### 3.5 Missing indexes for the queries actually run

The hot query shape is `WHERE ticker = ? AND interval = ? ORDER BY ts DESC` but
`price_bars` indexes `ts` alone (plus the composite PK). A
`(ticker, interval, ts DESC)` index would serve every `_latest_close`,
screener, and chart query directly.

---

## 4. Testing & CI

### 4.1 Zero unit tests on the web app 🟠

228 Python tests vs. **6 Playwright specs and no unit tests at all**. There is
no Vitest/Jest setup. Untested: every currency/percentage formatter, the
`compare`/`sortHref` logic in `/markets`, `safeRedirect` (an open-redirect
guard with no test), the trade and backtest forms, and every server action.

**Fix:** add Vitest + Testing Library, start with `safeRedirect`, the
formatters, and the server actions' validation branches.

### 4.2 CI blind spots

- **No coverage measurement or gate** on either app.
- **No dependency scanning** — no Dependabot/Renovate config, no `pnpm audit`,
  no `pip-audit`/`uv-secure`. `.github/` contains only `workflows/`.
- **No `alembic check`** — nothing catches model/migration drift, and there are
  already two merge migrations in `versions/`, which is where drift hides.
- **No `uv lock --check`** to catch a stale lockfile.
- **No Docker build** in CI — `apps/api/Dockerfile` is only exercised at deploy
  time on Render.
- **No accessibility or Lighthouse check** despite this being a chart-heavy UI.

### 4.3 Repository hygiene

No `CODEOWNERS`, no PR template, no issue templates, no `CONTRIBUTING.md`, no
branch protection artifacts — despite `CLAUDE.md` documenting a fairly precise
`main ← dev ← feat/*` workflow that nothing enforces.

---

## 5. Frontend

### 5.1 No error, loading, or not-found boundaries 🔴

`find app -name "error.tsx" -o -name "loading.tsx" -o -name "not-found.tsx"`
returns **nothing**. Every page is an async server component that fetches with
`cache: "no-store"`.

This matters a lot here specifically: the API runs on Render's **free tier**,
which spins down after ~15 minutes of inactivity and takes 30–60s to cold
start. Right now that's a raw Next.js error page on every route.

**Fix:** an `app/error.tsx` + `app/global-error.tsx` with a retry button, a
`loading.tsx` per route segment (skeletons), `not-found.tsx` for unknown
tickers, and a short retry-with-backoff in `lib/api/client.ts` for 502/503/504.

### 5.2 No caching strategy

Every `apiGet` is `cache: "no-store"`. EOD price bars change once a day —
`next: { revalidate: 3600, tags: ["bars"] }` on bars/symbols/news would cut
backend load dramatically and make cold starts far less visible.

### 5.3 Accessibility & mobile

No skip-link, chart components have no text alternative or `aria-label`, sort
headers don't expose `aria-sort`, and the data tables have no responsive
column collapse (IDEAS.md #16 flags this and it appears not to have been
done). The `LivePriceBadge` opens an `EventSource` with no
`prefers-reduced-motion` consideration and no cleanup on tab-hide.

### 5.4 Minor

- `app/api/export/trades/route.ts` builds CSV by string concatenation with no
  quoting/escaping and no formula-injection guard (`=`/`+`/`-`/`@` prefix).
  Fields are DB-controlled today, so it's latent rather than exploitable.
- The CSV export ignores currency entirely — a mixed-currency portfolio
  exports a meaningless `Total` column.

---

## 6. Architecture & maintainability

### 6.1 Documentation drift 🟠

- `CLAUDE.md` still describes the auth bridge as `X-Internal-Token` +
  `X-User-Id` headers and calls JWT "the documented upgrade target".
  `auth.py` has *already* been upgraded to Bearer JWTs. The guide actively
  misdescribes the system.
- `docs/IDEAS.md` lists ideas #1–#16 as future work. Essentially **all of
  them are shipped** (watchlist, snapshots, alerts, advanced orders,
  analytics, screener, backtesting, OAuth, CSV export, SSE, sentiment,
  leaderboard, JWT auth, rate limiting, e2e tests). It reads as a roadmap and
  is actually a changelog.
- `models/user.py` and `models/portfolio.py` docstrings still say "Phase 2
  keeps this thin" / "Phase 6 will write the recompute logic" for code that
  exists.

### 6.2 Duplicated trading logic

`execute.py` and `orders.py` each carry their own `_latest_close`,
`_get_or_create_position`, weighted-average-cost recompute, and
position-deletion logic. That duplication is exactly why §1.2's FX bug exists
in one and not the other. One `_apply_fill` helper fixes the bug and the
duplication together.

### 6.3 Inconsistent ownership model

Equity `Position` and `Trade` hang off `portfolio_id`; `OptionsPosition` and
`Alert` hang off `user_id`. Nothing breaks today because every user has exactly
one portfolio, but multi-portfolio support (an obvious next feature) would
require a migration. Normalize on `portfolio_id` now while it's cheap.

### 6.4 Inconsistent "today"

`_time.utcnow()` is the house standard, but `options/trade.py` and
`trading.py::get_portfolio_dividends` call `date.today()`, which uses the
server's local timezone while the scheduler runs on `America/New_York`. Around
midnight UTC these disagree. Route everything through `_time`.

### 6.5 Style nits worth a sweep

- `trading.py::get_portfolio_dividends` uses
  `__import__("decimal").Decimal(0)` and four function-local imports.
  `leaderboard.py` imports `HTTPException` inside two handlers.
- `select(User).where(User.public_profile == True)  # noqa: E712` →
  `.where(User.public_profile.is_(True))`.
- The `# type: ignore` / `# pyright: ignore` density on SQLModel `order_by`
  calls (~40 occurrences) suggests a small typed helper is worth writing.

### 6.6 No API versioning or client generation

Routes are `/v1/...` but there's no deprecation policy and the TS types in
`lib/api/types.ts` are hand-maintained against FastAPI's Pydantic schemas with
nothing checking they agree. Generating TS types from the OpenAPI schema in CI
(`openapi-typescript`) would make drift a build failure.

### 6.7 Deployment config gap 🟠

`infra/render.yaml` sets `ALPHA_VANTAGE_KEY`, `NEWSDATA_KEY`, `SENTRY_DSN`,
`NEXTAUTH_JWT_SECRET`, `INTERNAL_API_TOKEN` — but **not `ANTHROPIC_API_KEY`**,
which `apps/api/.env.example` documents and `services/sentiment.py` requires.
Headline sentiment scoring is therefore silently disabled in production: every
`news_articles.sentiment` written by the deployed scheduler is NULL, and the
`SentimentBadge` never renders. `SENTRY_TRACES_SAMPLE_RATE` is missing too.

---

## 7. Product gaps

- **Realized P&L / tax lots.** `execute_trade` deliberately doesn't recompute
  `avg_cost` on sells, so cost basis stays honest — but realized gains are
  never recorded anywhere. There's no "you made $X on this closed position",
  no FIFO/LIFO lot tracking, and `/trades` can't show per-trade P&L.
- **No cash deposits/withdrawals.** Everyone is permanently on $100k. That also
  means NAV-based returns are clean, so if deposits are ever added, the return
  math needs to switch to time-weighted returns.
- **Alerts are in-app only** and only evaluated hourly, weekdays 10:00–16:00 ET
  — an alert that triggers Friday at 16:30 waits until Monday. No email/push,
  no repeat/one-shot setting, no per-user cap on alert rows.
- **Options are long-only**, no spreads, no early exercise, no margin, and
  implied vol is 30-day historical vol (documented, but worth surfacing in the
  UI so users don't read it as a real IV).
- **No search.** With 32 symbols a table works; there's no typeahead for when
  the universe grows.
- **Leaderboard is trivially gameable** — return % over an arbitrary window
  with no risk adjustment and no minimum trading history. A one-lucky-trade
  account tops it. Rank on Sharpe, or require ≥30 snapshots.

---

## 8. Connecting the sentiment-analysis repo

This is worth designing deliberately, because the current sentiment path was
built as a feature (badge on a headline) rather than as a data pipeline.

### What exists today

`services/sentiment.py` calls Claude Haiku with a batch of ≤20 headlines and a
JSON-schema output config, returning `"positive" | "neutral" | "negative" |
None`. `ingest_news_for_ticker` calls it inline and stores the label in
`news_articles.sentiment` (a `VARCHAR(16)`). Failures degrade to `None`.

### Structural gaps for a second sentiment source

1. **No provider abstraction.** `ingest/news.py` imports `score_headlines`
   directly. Introduce a `SentimentProvider` protocol
   (`score(texts) -> list[SentimentScore]`) with `AnthropicProvider`,
   `HttpProvider`, and `NullProvider` implementations, selected by a
   `SENTIMENT_PROVIDER` setting. This is the one change that has to land first;
   everything else builds on it.

2. **The schema is too thin to hold a real model's output.** A single
   categorical column can't express a continuous score, a confidence, or which
   model produced it — so you can't re-score, compare models, or ship an
   upgrade without destroying history. Add:

   ```
   news_sentiment
     id, article_id → news_articles.id
     model          # "claude-haiku-4-5" | "finbert-v2" | ...
     label          # positive | neutral | negative
     score          # Numeric(6,4), -1.0 .. 1.0
     confidence     # Numeric(5,4), nullable
     scored_at
     UNIQUE (article_id, model)
   ```

   Keep `news_articles.sentiment` as a denormalized "current best" cache so
   existing reads don't change.

3. **No backfill path.** Rows ingested while `ANTHROPIC_API_KEY` was unset
   (which, per §6.7, is *all production rows*) stay NULL forever. Add
   `python -m stockviz.cli score-sentiment [--since DATE] [--model X]` plus a
   scheduler job, so a newly-connected provider can process the archive.

4. **Duplicate scoring.** The same article ingested under two tickers gets
   scored twice. Dedupe on the article `url` before dispatching.

5. **Only the headline is scored.** `summary` is fetched and discarded. Most
   sentiment models do meaningfully better on headline + lede.

6. **No retry, no cost ceiling.** `_classify_batch` catches everything and
   returns all-`None` on a single failure — one transient 429 silently drops 20
   articles. `tenacity` is already a dependency; use it. Add a daily
   article-count cap so a runaway ingest can't burn budget.

### Integration options

| Option | Shape | Best when |
|---|---|---|
| **A. Library** | Publish the sentiment repo as a Python package; `HttpProvider` → `LocalModelProvider` | Model is small (FinBERT-class) and CPU inference is fine |
| **B. Service** ✅ | Sentiment repo runs as its own service; `HttpProvider` POSTs `{texts: [...]}` and gets `[{label, score, confidence, model}]` | Model needs its own deps/GPU/scaling — **recommended** |
| **C. Shared DB** | Sentiment repo writes `news_sentiment` directly | Batch/offline scoring; but couples two repos to one schema — avoid |

Option B keeps the repos independently deployable and keeps StockViz's
dependency footprint small (no torch/transformers in the API image, which
matters on Render's free tier). The contract is small enough to pin as a
versioned JSON schema in `docs/`.

### Where sentiment should actually be *used*

Right now it renders a badge and nothing else. It's the most under-exploited
data in the system. In rough order of value-per-effort:

1. **A 7th vote in the recommendation engine.** `score_ticker` has six votes
   and a `VOTE_THRESHOLD` of 4. Add `_vote_positive_sentiment(...)` over the
   trailing-7-day mean sentiment for the ticker. Small, self-contained, and it
   makes `/recommendations` reflect news rather than price alone.
2. **A screener filter.** `sentiment_min` / `sentiment_max` alongside the RSI
   and momentum filters — the materialized `symbol_metrics` table from §3.3 is
   the natural home for a rolling sentiment average.
3. **`GET /v1/symbols/{ticker}/sentiment`** — a time series of daily mean
   sentiment, overlaid on the price chart on the ticker page. This is the
   demo-able feature: "here's the news mood plotted against the price."
4. **A `sentiment_threshold` backtest strategy.** Buy when 3-day mean sentiment
   crosses above +0.3, sell below −0.3. Once §1.6's benchmark exists, this
   answers "does news sentiment actually predict anything?" — a genuinely
   interesting result either way, and the strongest argument for the whole
   sentiment pipeline.
5. **A sentiment-driven alert type.** `Alert` already has direction + threshold
   semantics; extend it with `alert_type: price | sentiment`.

### Sequencing

```
0. Set ANTHROPIC_API_KEY in render.yaml           (unblocks everything; 5 min)
1. SentimentProvider protocol + settings switch   (no behavior change)
2. news_sentiment table + backfill CLI            (migration + job)
3. HttpProvider + documented JSON contract        (connects the other repo)
4. Rolling per-ticker aggregate + /v1 endpoint    (makes it queryable)
5. Recommendation vote / screener filter / chart overlay / backtest strategy
```

Steps 1–2 are worth doing even if the other repo never lands — they fix the
"production sentiment is silently NULL" problem and make the column meaningful.

---

## 9. Suggested order of work

**Now — correctness and safety**
1. Options in NAV (§1.1) — the ledger is wrong for a shipped feature
2. Startup assertion on production secrets (§2.1)
3. SSE session leak (§2.2)
4. FX in order settlement + dividends (§1.2, §1.3), via the shared `_apply_fill`
5. `ANTHROPIC_API_KEY` in `render.yaml` (§6.7)

**Next — resilience and load**
6. `error.tsx` / `loading.tsx` / retry-with-backoff (§5.1)
7. Batch markets endpoint (§3.1) + `--proxy-headers` (§2.3)
8. `DISTINCT ON` for latest closes; kill the N+1s (§3.2)
9. Advisory-lock guard on scheduler jobs (§3.4)

**Then — durability**
10. Vitest on the web app (§4.1); Dependabot + `alembic check` in CI (§4.2)
11. `materialized symbol_metrics` (§3.3)
12. Refresh `CLAUDE.md` and retire `IDEAS.md` into a changelog (§6.1)

**In parallel — the sentiment track**
13. §8 steps 1–3, then the recommendation vote and chart overlay
