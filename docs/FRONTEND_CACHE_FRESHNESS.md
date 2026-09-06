# Frontend cache freshness audit

Audited 2026-09-06 against the working tree and installed Next.js 16.3.1 runtime. The P0 leaderboard helper and marketing caller now use uncached API reads. This is a source audit, not a measurement of production cache ages or a deployment change. The API remains the authority for privacy, account state, and market-data provenance.

## Priority findings

1. **P0 — leaderboard disclosure must reach the live API (fixed).** The audit found the marketing `ProductTour` calling `getLeaderboard(3600)`, which allowed Next's shared Data Cache to return usernames without running the API's fresh database visibility check. The helper now unconditionally requests `no-store`, and the marketing TTL argument is removed; both public surfaces reach the API. A tag purge from the settings action alone cannot cover privacy changes committed through other API callers or replicas. Never reintroduce a shared cache of the final identifying leaderboard response.
2. **P1 — configured intervals are not hard freshness guarantees.** Bars, market summaries, and symbol lists opt into one-hour revalidation; news uses 15 minutes. There is no ingest-to-Next invalidation hook. A newly committed correction or ingestion can remain invisible until a later successful revalidation, and background refresh failures can extend staleness beyond the interval.
3. **P1 — views can combine different data generations.** Stock detail reads its current quote and indicators without a Next TTL, while chart bars use the one-hour Data Cache. Watchlist prices are uncached account reads while sparklines are cached bars. A displayed quote, chart, return calculation, and indicator bundle can therefore disagree temporarily after ingestion. A further response TTL for indicators would add another independently stale layer.
4. **P2 — reuse is uneven.** `/markets` and portfolio overview consolidate expensive reads, but marketing still fetches up to 14 separate bar histories for the ticker strip, and watchlists fetch one sparkline history per item. Different bar limits are distinct cache keys even when their underlying history overlaps.

## Helper and caller inventory

The policy below is the Next server fetch policy, not a promise about the age of the upstream data. [`client.ts`](../apps/web/lib/api/client.ts) defaults to `cache: "no-store"`. Supplying `revalidateSeconds` emits `next.revalidate`; tags identify entries for invalidation but do not execute invalidation. [`server.ts`](../apps/web/lib/api/server.ts) forces `no-store` for all authenticated requests.

| Helper | Next server policy / tags | Actual consumers and freshness implications |
| --- | --- | --- |
| [`getBars`](../apps/web/lib/api/bars.ts) | 3,600 seconds; `bars` | Stock chart and 252-day range, compare, watchlist sparklines, marketing hero/status/ticker/history/backtest preview. Ticker, interval, dates, and limit form separate URLs. This TTL also applies if a caller requests `1h` bars; the helper does not distinguish intraday freshness. |
| [`getMarketsSummary`](../apps/web/lib/api/markets.ts) | 3,600 seconds; `markets`, `bars` | `/markets` and marketing `ByTheNumbers`. Market page requests 30 sparkline days; the marketing default URL is a separate entry. |
| [`listSymbols`](../apps/web/lib/api/symbols.ts) | 3,600 seconds; `symbols` | Backtest, screener, compare, trade, orders, alerts, watchlist, replay, marketing hero/hero panel/ticker; also browser-side compare picker. New symbols and metadata changes have no explicit purge. |
| [`getLatestNews`, `getNewsForTicker`](../apps/web/lib/api/news.ts) | 900 seconds; `news` | `/news` and stock detail (8 articles). Different limits and tickers are separate entries. The source comment's ingestion cadence is not itself a freshness guarantee. |
| [`getRecommendations`](../apps/web/lib/api/recommendations.ts) | Default `no-store`; opt-in `recommendations` tag | `/recommendations` uses uncached filters and limit 100. Marketing tour requests 5 with 3,600 seconds; `ByTheNumbers` requests 1 with 3,600 seconds. Those are separate cached results. |
| [`screenSymbols`](../apps/web/lib/api/screener.ts) | Default `no-store`; opt-in `screener` tag | `/screener` and compare suggestions stay uncached. Marketing tour opts into 3,600 seconds for its fixed 30-day momentum query. |
| [`getLeaderboard`](../apps/web/lib/api/leaderboard.ts) | Unconditional `no-store` | `/leaderboard` and marketing tour both execute the live API request. The API may cache ranking inputs, but it checks current public visibility and names for every response. See the P0 finding above. |
| [`getIndicators`](../apps/web/lib/api/indicators.ts) | `no-store` | Stock detail combines selected indicator names and mandatory `rsi_14` into one request. The optional API computation cache always reads current PostgreSQL bars first and keys reuse by ticker, interval, parsed indicators, and every input timestamp/Decimal close. Its 300-second TTL controls retention, not permission to reuse an older database generation. Keep this frontend helper uncached. |
| [`getSymbol`, `searchSymbols`](../apps/web/lib/api/symbols.ts) | `no-store` | Stock detail and compare use symbol detail, including the latest quote. Compare's browser symbol picker injects `searchSymbols` as its default search function; blank searches make no request and nonempty searches use one attempt. |
| [`getQuotes`](../apps/web/lib/api/quotes.ts) | `no-store` | Trade ticket and alert creation. One request accepts multiple tickers; empty input makes no request. These are stored-data quotes, not a new guarantee of streaming prices. |
| [`listComments`](../apps/web/lib/api/comments.ts), [`getApiHealth`](../apps/web/lib/api/health.ts) | `no-store` | Stock discussion and the exported health helper, respectively. Health helper has no production call site in this tree; failures return a degraded status. |
| [`runBacktest`](../apps/web/lib/api/backtest.ts) | `no-store` POST; one attempt by default | Interactive backtest and marketing simulation preview. Marketing caches the bars used to choose its dates, but the simulation POST is uncached by this wrapper. Do not infer this from HTTP method alone. |
| Authenticated helpers in `trading`, `options`, `watchlist`, `alerts`, `earnings`, `journal`, `replay`, and profile helpers in `leaderboard` | Always `no-store` through `server.ts` | Account pages, stock account panels, settings, earnings, replay, journal proxies, and mutations. Keep portfolio/account responses out of a shared Data Cache. `types`, generated schemas, schema checks, and `index` do not introduce caches. |

`next.revalidate` is a Next server extension. A helper invoked directly in a browser, such as the compare symbol picker, does not thereby acquire the Next server Data Cache. Browser/proxy HTTP caching and existing rendered client state are separate layers. The journal proxy responses explicitly set `Cache-Control: private, no-store`; the alerts bell fetch explicitly requests `no-store`.

## What the installed runtime establishes

These semantics were checked in the installed `next@16.3.1` package under `node_modules/.pnpm/next@16.3.1_*/node_modules/next/dist/server/lib/`, rather than inferred from the helper comments:

- `incremental-cache/index.js`, `get`: a fetch entry becomes stale when its age exceeds its revalidation interval. It returns the stale data with an `isStale` flag.
- `patch-fetch.js`, stale-entry branch: ordinary requests can start `doOriginalFetch(true)` in `pendingRevalidates` and return the previously cached response. Static-generation revalidation has a separate foreground-refresh branch. Therefore a `3600` setting is a refresh threshold, not an absolute one-hour age limit.
- `patch-fetch.js` caches successful origin responses; failed background work is caught/logged. The application does not add a maximum acceptable source timestamp or a hard stale-data cutoff.
- `incremental-cache/index.js`, `generateCacheKey`: the URL and request properties enter the key. A shared `bars` tag does not merge `limit=2`, `limit=60`, and `limit=400` responses.
- `dedupe-fetch.js`: identical GET/HEAD requests can share work through React's request cache in a render context. URL and selected request properties matter; explicit signals and non-GET/HEAD methods bypass this mechanism. This is not a cross-request or cross-replica cache, and it does not consolidate different query URLs.

Consequently, an API TTL and a Next revalidation interval do not combine into a reliable maximum age. Next may fill its cache from an already-aged API result, then continue serving it during refresh. An ingest timestamp, bar timestamp, or recommendation `computed_at` describes data provenance more accurately than the cache interval alone. No production headers, CDN settings, or deployment cache-sharing behavior were measured in this audit.

## Invalidation paths present and absent

Application code contains **no invocation of `revalidateTag` or `updateTag`**. References to `revalidateTag` in the fetch wrapper and bars helper are comments only. There is no revalidation route among `app/api` handlers and no callback from API ingestion/scheduled jobs to a frontend invalidation endpoint. Thus `bars`, `markets`, `symbols`, `news`, `recommendations`, and `screener` are labels ready for future use, not a connected invalidation system.

Existing server actions call `revalidatePath` after their API write succeeds:

| Mutation | Paths explicitly requested for revalidation |
| --- | --- |
| Equity trade / pending order creation | Relevant combinations of `/portfolio`, `/trades`, `/trade`, `/orders`, and `/stocks/<ticker>` |
| Order cancellation | `/orders`, `/portfolio`, `/trade`, and optional stock path |
| Option open/close | `/portfolio`, `/trade` |
| Watchlist add/remove | `/watchlist`, stock path |
| Comment post/delete | Stock path |
| Alert create/delete/dismiss | Relevant combinations of stock path, `/alerts`, `/watchlist`, `/` |
| Profile visibility | `/settings` |
| Display currency | `/settings`, `/portfolio` |
| Replay actions | `/replay` and/or the affected replay session |

Path revalidation is useful for the action's affected rendered routes. It is not a general notification that every cached market-data URL changed, nor does it cover direct API writes, ingestion, or scheduled fills. Pages already open in another browser are not remotely erased or pushed new content by these actions. The privacy guarantee concerns fresh requests reaching the authoritative check; it cannot retract information already delivered.

If ingest invalidation is added later, trigger it after a durable successful write and account for every frontend cache instance. Map bars/corrections to `bars` and their affected derived results, metadata to `symbols` and market summaries, news/sentiment to their relevant news/derived results, and recommendation recomputation to `recommendations`. Failure/retry behavior and whether invalidation means immediate expiration or background refresh must be explicit. This audit does not implement that hook or authorize provider, deployment, or infrastructure changes.

## Request reuse and the next useful reductions

[`/markets`](../apps/web/app/(product)/markets/page.tsx) uses one summary request containing rows, sectors, and sparklines, replacing the earlier per-symbol bars pattern. [`loadPortfolioOverview`](../apps/web/lib/portfolio-overview.ts), used by dashboard and portfolio loaders, requests portfolio plus analytics together and falls back to the required portfolio alone if the combined request fails. This avoids duplicate valuation on the successful path while preserving fresh authenticated reads.

Stock detail explicitly reuses its chart-bars promise for the range calculation when the chart already covers at least 252 days. It also combines selected indicators with RSI into one deduplicated name set. When the chart window is shorter, it makes a second, distinct bars request for the range. Those two responses may be refreshed at different times.

Repeated identical `listSymbols()` requests across marketing components are candidates for render-level deduplication and shared Data Cache hits. In contrast, the ticker strip's up to 14 `limit=2` requests, hero's `limit=60`, status's `limit=1`, history panel, and tour's `limit=400` remain distinct. Watchlist similarly issues one `limit=30` request per item. A shared public market-summary load is a useful future consolidation where its shape supplies the required display values; a new shared cache of account data is not necessary for that reduction.

The API's privacy-safe ranking cache deliberately permits eventual ranking inclusion for a newly opted-in user on another replica until that replica refreshes. Current opt-outs and names are checked on every live API response. This distinction must remain explicit in product expectations and must not be hidden by a Next response cache.

## Verification scope

The audit traced `lib/api/*`, production helper call sites, server actions, API route handlers, and API/script revalidation references. Framework behavior was checked against the installed runtime files above. No populated database, external provider, production cache, or infrastructure was queried or changed for this source audit. This document adds no runtime behavior; the leaderboard helper/caller fix is a separate P0 code change covered by focused frontend regression tests.
