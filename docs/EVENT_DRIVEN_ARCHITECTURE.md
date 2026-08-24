# Event-driven architecture

StockViz uses Kafka for **asynchronous orchestration** of market ingest, news
ingest, and derived calculations. PostgreSQL remains the source of truth for
price bars, news, sentiment, metrics, and every financial ledger row.

Kafka is **not** a source of truth. Kafka is **not** in the trade commit path.

```
                         ┌────────────────┐
                         │  APScheduler   │
                         └───────┬────────┘
                                 │
                         durable requests
                                 │
                                 ▼
                             Postgres
                               Outbox
                                 │
                                 ▼
                               Kafka
               ┌─────────────────┴─────────────────┐
               │                                   │
               ▼                                   ▼
        Market Ingest                        News Ingest
               │                                   │
           PostgreSQL                          PostgreSQL
               │                                   │
        bars.refreshed                    article.ingested
               │                                   │
               ▼                                   ▼
             Kafka                               Kafka
               │                                   │
        Market Analytics                    Sentiment Worker
               │                                   │
        metrics + alerts                     sentiment row
                                                   │
                                           sentiment.scored
                                                   │
                                                   ▼
                                                 Kafka
                                                   │
                                                   ▼
                                         Sentiment Aggregate


Trading remains independently strongly consistent:

FastAPI → PostgreSQL ledger + outbox → COMMIT
```

## Control events vs domain events

**Control events** are durable work requests. The scheduler (or a CLI) writes
them to the outbox. They mean "please do this work," not "this fact is now
true."

| event_type | topic | key | producer | consumer group | side effect |
| --- | --- | --- | --- | --- | --- |
| `market.refresh.requested` | `stockviz.market.v1` | ticker | scheduler / CLI outbox | `stockviz.market-ingestion.v1` | fetch bars, upsert `price_bars` |
| `news.refresh.requested` | `stockviz.news.v1` | ticker | scheduler / CLI outbox | `stockviz.news-ingestion.v1` | fetch headlines, insert new `news_articles` |

**Domain events** record that PostgreSQL state changed. Downstream workers
derive metrics, alerts, or sentiment from them. They are not a second ledger.

| event_type | topic | key | producer | consumer group | side effect |
| --- | --- | --- | --- | --- | --- |
| `market.bars.refreshed` | `stockviz.market.v1` | ticker | market-ingest worker | `stockviz.market-analytics.v1` | ticker-scoped `symbol_metrics` + price alerts |
| `news.article.ingested` | `stockviz.news.v1` | ticker | news-ingest worker | `stockviz.news-sentiment.v1` | score one article |
| `news.sentiment.scored` | `stockviz.news.v1` | ticker | news-sentiment worker | `stockviz.sentiment-aggregate.v1` | ticker-scoped rolling sentiment |
| `trade.executed` | `stockviz.trades.v1` | portfolio_id | trading ledger (same COMMIT) | `stockviz.trade-activity.v1` | derived `portfolio_trade_activity` |

One `market.bars.refreshed` is emitted **per successful ticker refresh**, not
per OHLCV row. `ingest_ticker` may write hundreds of bars; a bar-per-event
stream would be noise.

`news.article.ingested` is emitted only for rows that were **actually
inserted**. Duplicate URLs hit `ON CONFLICT DO NOTHING` (Postgres
`RETURNING`) and produce no event.

## Why the scheduler no longer calls providers

`daily_price_refresh`, `hourly_top_movers`, and `news_refresh` enqueue
control events and commit. If Kafka is down at fire time, the request stays
in `outbox_events` until the publisher retries. The API stays healthy.

The scheduler does **not** publish to Kafka directly.

`hourly_top_movers` no longer evaluates alerts. Alerts run in market
analytics **after** refreshed bars are persisted.

## APScheduler vs workers (before / after)

| Job | Before | After |
| --- | --- | --- |
| `daily_price_refresh` | yfinance / Alpha Vantage per ticker | enqueue `market.refresh.requested` (`reason=daily`) |
| `hourly_top_movers` | ingest + evaluate all alerts | enqueue `market.refresh.requested` (`reason=hourly`) |
| `news_refresh` | Newsdata.io + optional inline sentiment | enqueue `news.refresh.requested` (skipped if no newsdata key) |
| `symbol_metrics_refresh` | full-universe RSI / 52w | **unchanged reconciliation** |
| `sentiment_aggregate_refresh` | full-universe rollup | **unchanged reconciliation** |
| `recommendations_refresh` | universe score | **unchanged** (not on Kafka yet) |
| FX, pending orders, dividends, options, snapshots | in-process SQL | **unchanged by design** |

## Incremental path vs reconciliation

Kafka consumers are the **freshness** path: one ticker, one event, fast.

Scheduled full-universe jobs are the **repair** path: drift, a missed
consumer, a worker that was down. This duplication is intentional.

Recommendations stay scheduled. They need both technicals and sentiment
across the universe; a `symbol.features.updated` event is a future option,
not this milestone.

Financial settlement stays on APScheduler/PostgreSQL. Those jobs mutate
ledger source of truth and have stronger ordering/accounting requirements.
That is a product choice, not a defect.

## Transaction boundaries

Every side-effecting consumer commits **one** PostgreSQL transaction that
includes:

1. domain writes (bars, articles, scores, metrics, alerts)
2. any **output** outbox row
3. the consumer **inbox** receipt `(consumer_name, event_id)`

Then it commits the Kafka offset. Offset-before-DB is forbidden.

Atomic units:

- market ingest: `price_bars` upsert + `market.bars.refreshed` outbox + inbox
- market analytics: ticker metrics + matching alerts + inbox
- news ingest: new `news_articles` + one `news.article.ingested` per insert + inbox
- news sentiment: `news_sentiment` + denormalized article label + `news.sentiment.scored` + inbox
- sentiment aggregate: ticker `symbol_metrics` sentiment columns + inbox
- trade execute: ledger + `trade.executed` outbox (FastAPI request transaction)

Provider HTTP runs **before** the DB transaction (fetch, then persist).

## Delivery semantics

Publication and consumption are **at-least-once**.

- Crash after DB commit, before offset commit → Kafka redelivers → inbox skip.
- Crash after provider fetch, before DB commit → may re-fetch; DB stays consistent.
- Duplicate scheduled requests have **new** `event_id`s. Bars upsert; article
  URLs stay unique. Re-fetching a read-only provider is acceptable.
- A failed provider call does **not** claim success. The offset stays
  uncommitted and the worker backs off (`kafka_retry_backoff_seconds`,
  default 2s). No tight retry loop. There is no retry topic / DLQ in this
  milestone; a poison payload can stall that partition until fixed.

## Sentiment disabled

`NullProvider` (`SENTIMENT_PROVIDER=none`, or no real key) is a first-class
configuration. The sentiment worker:

- consumes `news.article.ingested`
- writes the inbox receipt
- does **not** emit `news.sentiment.scored`

Articles remain stored. `backfill_unscored` / `score-sentiment` CLI still
work later when a provider is configured.

If a real provider is configured but the HTTP call fails, the worker does
not write a fake score and does not commit the offset (retry with backoff).
The article row is untouched.

## Local topics

Compose profile `events` (`pnpm events:up`) runs Kafka in **KRaft** mode
(no ZooKeeper). Auto-create is **off**. Init creates:

- `stockviz.trades.v1`
- `stockviz.market.v1`
- `stockviz.news.v1`

Development: **3 partitions**, replication factor **1**.

## Commands

```bash
pnpm events:up
pnpm events:publisher          # long-running outbox → Kafka
pnpm events:market-ingest
pnpm events:market-analytics
pnpm events:news-ingest
pnpm events:news-sentiment
pnpm events:sentiment-aggregate
pnpm events:down
```

`--once` flags exist on the Python modules and on `python -m stockviz.cli`.
Manual ingest CLIs (`ingest`, `score-sentiment`) still talk to providers
directly for one-off repair.

## What this milestone is not

No Kubernetes, Helm, Schema Registry, Kafka Connect, Debezium, Flink,
retry topics, or event-sourced trading ledger. Price bars live in
PostgreSQL. Consumers are processes you run, not a mesh.
