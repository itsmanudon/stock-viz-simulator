# PostgreSQL-first caching architecture

Milestone: 2026-09-06. PostgreSQL remains durable truth. Kafka/outbox remains the event pipeline. No provider/cutover work, Redis queues, production Redis deployment, or durable-data migration is part of this change.

## Decision and priorities

P0 removes unnecessary history scans before adding another system. PostgreSQL uses the existing `ix_price_bars_ticker_interval_ts` index with a correlated `LATERAL ... ORDER BY ts DESC LIMIT N` per requested symbol. Markets use N requested sparkline bars; momentum uses at most days+1; portfolio valuation uses one. SQLite retains the single window-query fallback. This is one SQL query, not N application/database round trips. The symbol foreign key guarantees the lateral outer symbol set; inactive holdings remain priceable. Daily interval, short/missing histories, zeros, Decimal arithmetic and chronological output are unchanged. Screener candidate LIMIT still precedes momentum filtering.

The authenticated `/v1/portfolio/overview` response combines `{portfolio, analytics}` using one valuation. Existing individual endpoints use the same response builders. Both dashboard loaders use the combined endpoint, without any persistent private-data cache. Analytics failure can still fall back to the required standalone portfolio; this exceptional path repeats valuation. No changes to FX, reservations, options valuation, missing-data handling, allocation, risk formulas, or snapshot semantics were made.

Leaderboard ranking candidates retain the existing one-hour process cache, but cached data does **not authorize disclosure**. Every response performs a fresh scalar database query for committed visibility and current names after any cache fill, filters, then re-ranks and limits. Profile mutations invalidate the local ranking timestamp **after successful commit**. Another replica's stale ranking cache cannot bypass visibility. Database failures fail closed here. The privacy check linearizes at its SQL statement under PostgreSQL READ COMMITTED; it cannot retract an already-sent response. New opt-ins on another replica may retain the existing ranking refresh delay. All Next leaderboard callers, including marketing, use `no-store`.

P1 is a deliberately narrow, optional, local **indicator computation** pilot. P0 leaves public AAPL/NVDA indicator math materially more expensive than its approximately 1 ms database reads. The pilot therefore keeps those cheap reads and reuses only the pure result for identical inputs. It does not cache market summaries, quotes, portfolios, news, options or recommendations simply because Redis is available.

## Cache inventory and freshness classes

| Family/data | Source of truth | Layer / current decision | Freshness and retention | Invalidation / risks |
| --- | --- | --- | --- | --- |
| Public indicator bundle, ≤1,000 bars and ≤8 requested names | Current PostgreSQL bar query + unchanged indicator algorithm | Optional Redis computation result | Exact-input class: 300 s retention, **zero additional database-generation staleness** | Every call rereads bars; a changed timestamp/close/window/interval/names changes the key. No event delivery dependency. Large requests calculate normally. |
| Markets/movers/sparklines | Symbols + price bars | Optimized bounded PostgreSQL query; no Redis | Latest persisted daily inputs | Next has a separate legacy one-hour policy, discussed below. |
| Momentum screener | Materialized symbol metrics + recent bars | Optimized PostgreSQL; no Redis | Existing analytics generation + requested N-bar return | Preserve candidate-limit semantics; no new response TTL. |
| Quotes, symbol detail | PostgreSQL latest bars/metadata | Database, no Redis pilot | Existing read semantics | Do not hide current quote semantics behind an arbitrary TTL. |
| Symbol lookup/company metadata | PostgreSQL symbols | Existing Next symbol-list cache; Redis deferred | Existing one-hour Next revalidation | Cheap/small current dataset; no proven incremental Redis ROI. |
| Recommendations/signals | PostgreSQL materialized recommendations | Database + existing opt-in marketing Next cache | Analytics generation | Recalculation already durable; separate Redis TTL not justified by this pilot. |
| Historical daily/intraday bars | PostgreSQL price bars | Bounded DB reads + existing Next policy | Completed sessions are **correctable**, not immutable | Historical corrections cannot be detected from latest timestamp/count alone. Large responses have serialization cost. |
| Leaderboard ranks | PostgreSQL snapshots | Existing process-local ranking cache | 3,600 s ranks; fresh DB visibility/names every response | Never cache final identifying response in Next/Redis. Opt-in inclusion remains eventual. |
| Portfolio summary/NAV/allocation/risk | PostgreSQL portfolios/positions/snapshots/FX/orders/options | Request-local shared valuation; no Redis | Fresh request-local valuation | Strict authenticated scope. Never reuse one user's valuation for another. |
| Orders, buying power, trades, option execution | PostgreSQL transactional state | No cache | Transactional correctness | Durable row locks/reservations remain authoritative. |
| News/sentiment/options read results | PostgreSQL/provider-ingested records | No pilot/performance recommendation | Not established from representative populated data | Local audit datasets were empty; no speed or hit-rate claims. |
| Backtest result | Pure computation over PostgreSQL input | No cache | Exact selected historical inputs | No durable result-retrieval endpoint was found; do not alter backtest math. |

No L1 financial cache duplicates the Redis pilot. Pure static metadata such as Pydantic schema fingerprints can remain process-local. Existing local rate limits remain per-replica; shared rate limiting is a separate scale-driven decision. PostgreSQL scheduler locks, Kafka consumer groups, outbox/inbox idempotency, and JWT sessions are unchanged.

## Exact-input key and serialization

`<CACHE_NAMESPACE>:indicators:v1:<sha256>`; default namespace `stockviz:local:v1`.

The digest binds ticker, interval, ordered parsed indicator names/periods, and **every selected (ISO timestamp, Decimal close string)**. The selected bars already encode range, limit, additions, deletions and corrections. Two differently written URLs producing identical inputs may safely share computation. Names retain ordering/repetition semantics. No user identifiers, credentials, raw query strings, or private data are in these keys.

The cache stores a debuggable JSON envelope: envelope version, full key, Pydantic response-schema fingerprint, absolute expiration, and `model_dump_json()` payload. Hits validate the envelope and `model_validate_json()` response. Decimal input hashing does not round to float; generic cache serialization preserves Decimal strings. Indicator outputs remain the existing algorithm's floats, with no new financial conversion. Naive daily session timestamps remain naive labels; timezone offsets remain explicit when present. No pickle or binary format is introduced. Maximum envelope size is 256 KiB.

Change the family computation version when algorithm semantics change, even if the response schema does not. Schema fingerprinting protects payload-shape changes, not algorithm changes. A namespace version bump makes old keys unreachable; TTL/LRU reclaims them.

## Durable commit and event behavior

```text
market event / CLI / direct durable correction
    -> PostgreSQL transaction commits (existing outbox/inbox semantics)
    -> next indicator request reads its current selected PostgreSQL bars
    -> exact input digest differs when calculation inputs differ
    -> miss, compute, best-effort Redis set

same durable input digest -> validated Redis hit
Redis missing/unavailable -> unchanged computation
```

There is no PostgreSQL/Redis dual write and no precommit invalidation. A rolled-back writer does not change another request's input digest. A request concurrent with a commit returns a calculation of its database statement's snapshot, just as before caching. An older in-flight fill writes only its old content key and cannot overwrite the corrected input's result. Unrelated OHLC/provenance changes that do not change timestamp/close do not change this pure close-only algorithm's result.

The original audit considered generation-key invalidation. After P0, retaining cheap DB input reads is a safer, smaller pilot: historical corrections and every existing writer are covered without adding event hooks or cache invalidation retries. **Tradeoff: query count and DB time are not reduced by this Redis pilot.** PostgreSQL optimizations provide the DB-work reduction; Redis provides measured application-compute reduction only.

## Next.js interaction

See [the frontend freshness audit](FRONTEND_CACHE_FRESHNESS.md). Indicator and authenticated helpers stay `no-store`, so there is no independently stale Next TTL over the pilot. The leaderboard helper is now unconditionally `no-store`.

Existing bars/markets/symbol-list revalidation is 3,600 s and news is 900 s; selected marketing screener/recommendation calls also opt into caching. Tags currently have **no ingest-connected invalidation hook**. Next revalidation is not a hard age limit: background refresh/failure can serve older data. Quotes, charts and indicators can consequently display different generations. This pre-existing market-data presentation risk is documented, not silently made worse by Redis. A follow-up should adopt an explicit frontend freshness contract or post-commit, retryable invalidation before claiming an end-to-end financial freshness bound.

## Failure and concurrency contract

- Disabled: ordinary calculation, no Redis import/network requirement at request time.
- Enabled but URL/password absent or malformed: fail configuration early. `production`/`prod` explicitly reject pilot enablement.
- Missing/restarted/evicted cache: miss and compute from current database inputs.
- Corrupt, oversized, expired, wrong-key or wrong-schema value: count invalid, recompute, overwrite best-effort. No stale-if-error.
- Transport/DNS/pool failure: bounded command wait, circuit opens for 30 s; calculate normally. No application retries of Redis commands. PostgreSQL/loader errors are **not** swallowed.
- Concurrent misses: duplicate pure calculations are allowed; identical inputs produce equivalent values. No distributed locks, job prevention, queue, or single-flight correctness dependency is introduced. Cache retention never slides on a hit.
- TTL is anchored before the loader. Slow fills whose retention has expired are not published. Absolute envelope expiry still rejects delayed background sets.

The transport pool is capped at eight connections per process, with 20 ms socket/connect timeouts and a 40 ms caller wait per command. An eight-permit executor prevents an unbounded queue; an exhausted budget/capacity bypasses Redis. A stopped-container DNS lookup during the initial pilot demonstrated why socket timeout alone was insufficient. Timed-out work can continue until the OS/client completes it, and Python may wait for these workers during graceful interpreter shutdown. This is a documented operational limitation, not a financial or normal-read dependency. See the benchmark report for final outage measurements.

## Local setup and security

Redis is an opt-in Compose `cache` profile, not an API readiness dependency. It uses `redis:7.4.11-alpine`, loopback-only host port `16381`, a 256 MiB container cap, `maxmemory 128mb`, `allkeys-lru`, `maxclients 128`, healthcheck, no RDB/AOF and no volume. Ordinary `db:up`/application reads do not require it. The image was updated from the initially available 7.4.1 to the August 2026 security patch before final pilot measurements. Continue reviewing patch releases; a pinned tag is not a permanent security guarantee. [Official 7.4 release notes](https://redis.io/docs/latest/operate/oss_and_stack/stack-with-enterprise/release-notes/redisce/redisce-7.4-release-notes/).

1. Generate a local password; set `REDIS_PASSWORD` in ignored `infra/.env`. Never commit it.
2. Start `docker compose -f infra/docker-compose.yml --profile cache up -d redis`.
3. Native API: copy documented options from `apps/api/.env.example`, use `REDIS_URL=redis://127.0.0.1:16381/0`, matching password, `CACHE_BACKEND=redis`. Compose API uses service hostname `redis`.
4. Keep `CACHE_BACKEND=none` to disable the pilot. Changing backend/credentials/namespace requires restarting the API process because settings/factory are memoized.

Plain Redis transport is limited to the isolated local network. `rediss` is supported for a future TLS-reviewed deployment, but this milestone forbids production enablement. Credentials are separate from the URL; URL credential/query overrides are rejected. Do not publish Redis in production or log keys/payloads/passwords. Application cache-error logs contain only a fixed event, family, operation and exception type.

Debug through a local administrative client using environment-based authentication, not a password pasted into command arguments. Use `SCAN` scoped to the configured namespace plus `TYPE`, `PTTL`, `MEMORY USAGE`, `INFO memory/stats/clients` and `SLOWLOG GET` where authorized. To flush the pilot, prefer a namespace version bump. If deleting keys, verify the isolated instance and exact namespace first, then SCAN/delete only that namespace; never run `FLUSHALL` against a shared server. Redis restart intentionally discards only disposable computation results.

## Observability

`get_cache().stats()` exposes thread-safe per-process counters used by the benchmark: hits, misses, sets, errors, invalid, bypass, commands, get/set command counts, cumulative command latency, backend-worker CPU and hit ratio. There is one family (`indicators`), so no unbounded ticker/user labels. Map these to `cache_hits_total`, `cache_misses_total`, `cache_set_total`, `cache_errors_total` when exporting. The benchmark correlates each request's cache outcome with ASGI latency, query count, DB cursor time and endpoint plus Redis-worker CPU. No successful-hit logging is emitted.

Redis `INFO` supplies evictions, used memory/RSS, connected clients and command statistics. The pilot records actual `MEMORY USAGE` for its keys. There is no new public metrics route or production monitoring infrastructure. Before production consideration, export per-replica counters and latency histograms through the existing telemetry stack, aggregate ratios from counters, and alert on sustained errors/miss storms/evictions/connection pressure. An exporter/dashboard is a **remaining production gate**, not something this local experiment pretends to deliver.

## Economics and production gates

See [measured results and cost assumptions](benchmarks/2026-09-06-caching.md). The current deployment audit found one Railway API and one web service plus PostgreSQL and a nightly cron; Kubernetes definitions support two API replicas/HPA to five and independent Kafka workers. No production Redis exists or was deployed. Local caches are not global rate limits or cross-replica invalidation mechanisms.

Do not assume fewer CPU cycles lower a predominantly idle-memory bill. Redis adds memory, operational work and another failure mode; the pilot deliberately saves no database queries. Production consideration requires observed traffic/key reuse, post-P0 capacity evidence, real telemetry, deployment/TLS/ACL and memory sizing review, and benefit that justifies incremental recurring cost. Provider work remains separate.
