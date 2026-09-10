# Repository-specific questions

The highest-value set: an interviewer who reads your code will ask these,
and nobody can answer them from a textbook.

---

## Foundation

**Q. What does the `(ticker, ts, interval)` primary key on `price_bars` guarantee?**
> One bar per symbol per timestamp per interval. That's what makes ingest
> idempotent — `ON CONFLICT DO UPDATE` means a replayed Kafka event
> rewrites the same row instead of duplicating market history.

**Q. Why is `interval` in the key when only `1d` is written?**
> So intraday intervals can be added later without a schema migration.

**Q. Why does `/live` not touch the database when `/health` does?**
> Liveness failure restarts the pod; readiness failure only removes it from
> the Service. A database outage should do the second, never the first —
> otherwise a Postgres blip restarts every API pod at once and adds a
> reconnect storm to a struggling database.

**Q. What happens if `INTERNAL_API_TOKEN` differs between web and API?**
> Every authenticated `/v1` call 401s. The web server signs the bridge JWT
> with it and FastAPI verifies with it; they must be identical.

**Q. Where does the browser store the API credential?**
> It doesn't. The token is minted server-side in `lib/api/server.ts`, which
> is `import "server-only"` — importing it client-side is a build error.

---

## Strong SWE

**Q. Why is `apply_fill` the only function that mutates cash and positions?**
> Because when market orders and pending settlement had separate copies,
> only one of them converted native currency to USD. One fill path means
> one place for that invariant to live.

**Q. What does `exclude_order_id` do, and why is it needed?**
> Pending BUYs reserve cash and pending SELLs reserve shares, and
> spendability is checked against available (balance minus reservations).
> When a pending order fills, it must consume *its own* reservation while
> still respecting every other order's — otherwise it would be blocked by
> money it had itself set aside.

**Q. `settle_pending_orders` takes a `session_date`. Why?**
> To refuse to fill against a stale close. If the latest bar predates the
> session, orders stay pending. A failed price refresh should delay a fill,
> not fill it at yesterday's price.

**Q. Why can Kafka consumers not write to `portfolios` or `positions`?**
> Delivery is at-least-once, so a duplicate event could double-spend.
> Consumers write only derived state — metrics, sentiment, activity
> counters — all of which are safe to recompute.

**Q. Why does `enqueue_event` not commit?**
> So it joins the caller's transaction. That's the entire outbox pattern —
> committing separately would reintroduce the dual write.

**Q. Two users create their first portfolio simultaneously. What happens?**
> `portfolios.user_id` is unique. One insert wins, the loser catches the
> violation and re-reads the winner's row. The database arbitrates instead
> of the application locking.

**Q. Why is the news query the company name rather than the ticker?**
> Newsdata.io returns far better results for "Amazon.com Inc." than "AMZN".
> `scheduler.company_name_map()` resolves it from `symbols.name` with
> `seed-data/companies.json` layered on top — the seed file isn't in the
> API image, so before the database lookup existed the query silently
> degraded to the bare ticker.

**Q. Why does `upsert_bars` chunk at 1000 rows?**
> `price_bars` binds 9 parameters per row and Postgres caps a statement at
> 65535 — about 7280 rows. A full-history fetch is ~11k bars, so a single
> statement failed outright against Postgres.

---

## Advanced

**Q. Your consumer doesn't commit the offset when a handler fails. Is the record retried?**
> It is now. It wasn't before — and that's the bug I'm proudest of finding.
> `poll()` advances the consumer's position regardless of commits, so the
> next poll returned the *following* record; once that committed, the
> committed offset moved past the failed one and it was gone. I now seek
> back to the failed offset. See
> [ADR-0005](../../adr/ADR-0005-rewind-on-handler-failure.md).

**Q. That means a poison record stalls the partition. Isn't that worse?**
> It's louder, not worse. There's no dead-letter topic, so the alternative
> is silently dropping a market bar. For financial data a visible stall
> beats an invisible gap. A DLQ with bounded retries is the real fix and
> it's on the roadmap.

**Q. Two market-data providers write the same logical bar. What happens?**
> Last writer wins — `upsert_bars` overwrites on conflict, including the
> `source` column. Alpha Vantage is only attempted when yfinance returned
> no rows, so it's rare, but the providers aren't reconciled and there's no
> bar-version history. That's documented in
> [market-data semantics](../../database/market-data.md).

**Q. What happens during a stock split?**
> Nothing good, and it's explicit: `auto_adjust=False`, so bars are stored
> **unadjusted**. A split leaves a discontinuity, positions held across it
> have a mismatched `avg_cost`, and backtests show a spurious jump. Splits
> aren't detected or adjusted for anywhere. Dividends *are* modelled
> separately as declared payouts.

**Q. How would you avoid storing an incomplete daily bar?**
> Today it relies on job timing — the refresh runs 16:30 America/New_York,
> after the close — with no "is this bar final?" check and no exchange
> calendar. A manual mid-session `cli ingest` can store a partial bar,
> which a later run overwrites. I'd add a market calendar and refuse to
> write a bar for a session that hasn't closed.

**Q. Your rate limiter is in-process and the API HPA goes to 5 replicas. What's the real limit?**
> Up to 5× the configured one, and it resets on every restart. slowapi's
> default storage is in-memory and there's no shared store. It's recorded
> as a limitation; a Redis-backed limiter is the fix, and it's the only
> thing I'd currently add Redis for.

**Q. Your scheduler is `replicas: 1`. Why also take an advisory lock?**
> Because `replicas: 1` is approximately-one, not at-most-one — a rolling
> update or node partition can briefly run two pods. Two schedulers firing
> `pending_orders_settlement` would fill the same order twice.

**Q. Your consumer HPA maxes at 3. Coincidence?**
> No — it matches `MARKET_TOPIC_PARTITIONS = 3`. A consumer group can't
> have more active members than partitions, so a fourth pod would consume
> nothing while still holding database connections.

**Q. Could you just raise the partition count to scale further?**
> Not without a correctness window. Partition is `hash(key) % count`, so
> rehashing moves keys to new partitions while their history stays behind,
> and per-key ordering breaks during the transition. The Strimzi manifest
> carries that warning in its own annotation.

**Q. How many Postgres connections does a full deployment open?**
> SQLAlchemy defaults give ~15 per process. At maximum scale — 5 API, 1
> scheduler, 1 publisher, 6 consumer types up to 3 replicas — that's well
> past the default `max_connections = 100`. There's no PgBouncer. It's a
> scale-out ceiling rather than a traffic ceiling.

**Q. `PriceBar.ts` — is that a UTC instant?**
> No, and it's worth being precise: it's the provider's session date with
> tzinfo stripped. The columns are `TIMESTAMP` without time zone and the
> Python convention is naive UTC, so `ts` is really a day key. Everything
> downstream treats it consistently, but adding intraday intervals would
> force it to be revisited.
