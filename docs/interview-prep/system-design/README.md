# System-design exercises

Each exercise is worked as an interview would be, then **compared against
what StockViz actually does**. That comparison is the valuable part: you
can defend a design you have built and explain where it diverges from the
textbook answer and why.

| Exercise | Core tension |
| --- | --- |
| [Market-data ingestion](./market-data-ingestion.md) | Provider flakiness vs. data completeness; idempotency at scale |
| [Real-time price delivery](./real-time-price-delivery.md) | Fan-out to many clients; push vs. pull; connection cost |
| [Stock alerts](./stock-alerts.md) | Evaluating many rules against a moving stream, exactly once |

## How to use these

1. Read the requirements, then **design it yourself on paper** (20–30 min).
2. Read the worked design and diff against yours.
3. Read the "what StockViz does" section — that's your evidence base.
4. Answer the follow-ups out loud.

## The framework

Interviewers grade the process more than the diagram:

```
1. Clarify        — scope, users, what "done" means
2. Functional     — what it must do
3. Non-functional — scale, latency, consistency, availability
4. Estimate       — back-of-envelope; drives every later choice
5. API            — the contract
6. Data model     — keys and access patterns first
7. Components     — boxes and arrows
8. Deep dive      — the interviewer picks; be ready for any box
9. Bottlenecks    — where it breaks first
10. Trade-offs    — what you gave up, deliberately
```

Steps 4 and 10 are where most candidates are weak. Estimation determines
whether you need Kafka or a cron job, and the honest answer for StockViz's
own volume is "a cron job" — which is exactly the kind of self-aware
trade-off that lands well.

## Shared numbers

Reuse these so estimates stay consistent:

| Quantity | Value |
| --- | --- |
| US-listed symbols | ~8,000 |
| Trading days/year | ~252 |
| One daily bar row | ~100 bytes |
| All symbols, 1 day | ~800 KB |
| All symbols, 10 years | ~2 GB |
| All symbols, 1-minute bars, 1 year | ~800 GB |

The last row is the one that changes architectures. Daily bars for the
entire US market are **trivial** — a few gigabytes, fits in RAM. Intraday
is a different system. Say this early; it reframes the whole problem.

**StockViz today:** a few dozen symbols, daily bars only. Genuinely small.
