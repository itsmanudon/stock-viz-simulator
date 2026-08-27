# Simulation execution kernel

SIM-01 introduces a **pure, deterministic execution engine**: given an order
intent, an observable market snapshot, and an execution profile, should this
order fill, at what price, and why?

This document describes that kernel. It does **not** claim that live paper
trading already uses it.

## Status

| Layer | SIM-01 |
| --- | --- |
| Pure kernel (`apps/api/src/stockviz/services/simulation`) | Implemented |
| `legacy_close` profile matching current fill rules | Implemented |
| Live `execute_trade` / market fills | **Unchanged** — still `services/trading/execute.py` |
| Live pending-order settlement | **Unchanged** — still `services/trading/orders.py` |
| Kafka `trade.executed.v1` | **Unchanged** |
| Database / API / frontend | **Unchanged** |

PostgreSQL remains the source of truth. Kafka is not authoritative for
execution. Trade and accounting mutations stay synchronous and transactional.

## Why execution is separated from accounting

Two different questions used to live in the same functions:

1. **Market execution** — given this order and this observable price, does it
   fill, and at what price?
2. **Account validity** — does this portfolio have the cash, shares, FX rate,
   and reservation capacity to accept that fill?

Mixing them makes it impossible to replay, backtest, or vary execution
assumptions without also mutating the ledger. The kernel answers only (1).

```text
simulation.engine.evaluate_order
    → should / how does this order fill?

trading.execute / trading.orders
    → can this account financially execute the fill?

database transaction
    → commit cash / positions / trade / order state

Kafka outbox
    → asynchronous derived processing after committed state
```

The kernel does **not** debit cash, mutate positions, check buying power,
reserve shares, convert FX, write trades, or publish events. Insufficient
cash or shares remain trading-layer failures (`InsufficientCash`,
`InsufficientPosition`), not execution-kernel states.

## Deterministic input / output

```text
decision = evaluate_order(order, market, profile)
```

Identical `OrderIntent`, `MarketSnapshot`, and `ExecutionProfile` values
always produce an equal `FillDecision`. The function reads no clock, RNG,
environment, database, or network. If a future profile needs "current time",
that time must be passed in explicitly (today it is not needed).

Outputs are explicit:

| `FillStatus` | Meaning |
| --- | --- |
| `FILLED` | Remaining quantity fills at the snapshot close |
| `NOT_TRIGGERED` | Snapshot is eligible, but the limit/stop/target condition is false |
| `INELIGIBLE` | Snapshot must not influence this order (time, ticker, unsupported side, unknown profile) |

Account-level rejection is intentionally absent. A fill decision is not a
trade.

Every decision carries an `ExecutionTrace` (`profile`, `model_version`,
reference/fill prices when they were allowed to be observed, `reason`,
`assumptions`).

## `MarketSnapshot.observed_at`

`observed_at` is **not** "whatever timestamp the vendor put on the bar."
Daily provider timestamps are ambiguous (session date vs close print vs
ingest time). The kernel treats `observed_at` as:

> The earliest simulation time at which this snapshot is allowed to influence
> execution.

That is the anti-lookahead seam for later replay (SIM-05 / SIM-06). A caller
that wants "this 1d bar may be used from the session close onward" must pass
that close time, not the bar's open, and not `datetime.now()`.

OHLC fields are present on the snapshot so later profiles can use them. The
`legacy_close` profile **does not** read `open` / `high` / `low` for triggers
or fill prices. Volume is unused.

## Temporal eligibility

If `market.observed_at < order.submitted_at`, the engine returns
`INELIGIBLE`. It does not fill retroactively from a snapshot that was only
knowable before the order existed.

Equal timestamps are eligible: the snapshot and the order become knowable at
the same instant.

The kernel does **not** implement the trading job's `session_date` freshness
guard (leave pending when the latest bar's calendar date is before today).
That is an operational ingest concern, not a fill-price rule. SIM-02/SIM-03
must keep that guard in the trading layer unless a later profile models it
explicitly.

## `legacy_close` (v1)

The only implemented profile. `name = "legacy_close"`, `model_version = "v1"`.

It reproduces **current** StockViz paper-trading fill economics. It does not
improve them.

| Order | Trigger | Fill price |
| --- | --- | --- |
| MARKET buy / sell | Snapshot is eligible | `snapshot.close` |
| LIMIT buy | `close <= limit_price` | `snapshot.close` |
| LIMIT sell | `close >= limit_price` | `snapshot.close` |
| STOP_LOSS (sell-only) | `close <= trigger` | `snapshot.close` |
| TAKE_PROFIT (sell-only) | `close >= target` | `snapshot.close` |

Limit and trigger share one field (`limit_price`) because that is how
`pending_orders` is stored today. Stop-loss and take-profit buy orders are
`INELIGIBLE` (current `create_pending_order` rejects them).

Assumptions recorded on every `legacy_close` trace:

- Uses stored 1d close
- No spread model
- No slippage model
- No partial fill model
- Does not use same-day OHLC high/low touches

Unknown profile names return `INELIGIBLE`. They do not silently fall back to
`legacy_close`.

## Current EOD limitations

Live paper trading still:

- Fills market orders at the **latest stored 1d close**
- Settles pending limit/stop/take-profit once per weekday after the daily
  refresh, at that session's close, not at the trigger
- Has no bid/ask, last trade, or order book
- Does not model latency, commissions, or liquidity
- Uses a simulated SSE quote that is **not** a fill source

Those limitations remain after SIM-01 because SIM-01 does not change runtime
paths. See [KNOWN_LIMITATIONS.md](./KNOWN_LIMITATIONS.md).

## Why same-day OHLC touches are not used

A tempting "improvement" for limits is:

- BUY LIMIT triggers when `low <= limit`
- SELL LIMIT triggers when `high >= limit`

That is **incorrect** for live paper orders against a daily bar.

If a user submits a buy limit at 14:00 and the daily low printed at 11:00,
the daily OHLC cannot prove the touch happened after submission. Using the
full-day high/low would create impossible pre-submission fills.

`legacy_close` therefore uses **close-only** comparison, matching
`services/trading/orders.py::_should_fill`. Future replay/backtest profiles
may use **next-bar** OHLC under explicit, documented assumptions. They must
not silently replace live EOD settlement.

## Future execution profiles (not implemented)

These names are reserved for later SIM work. They are **not** implemented
and must not be passed to `evaluate_order` expecting a fill.

| Profile | Intent (future) |
| --- | --- |
| Ideal | Frictionless fill at a stated reference (e.g. next mid or next close) once eligible |
| Retail Realistic | Spread, delay, and modest slippage typical of a retail paper/broker path |
| Conservative | Adverse selection: worse of bid/ask, extra slippage |
| Stress | Wide spreads, partial fills, liquidity caps |
| Custom | Caller-supplied parameters once the profile schema exists |

Do not add stub classes that pretend these work. SIM-04 is the versioned
profile + trace persistence task.

## Later program (not this PR)

| ID | Scope |
| --- | --- |
| SIM-02 | Route current **market** fills through `legacy_close` (adapter only; economics unchanged) |
| SIM-03 | Route **pending** conditional orders through the same kernel |
| SIM-04 | Versioned profiles + persist execution traces |
| SIM-05 | ReplaySession + simulation clock |
| SIM-06 | Blind historical market replay |
| SIM-07 | Post-trade forensic analytics |
| SIM-08 | Backtester uses the same execution kernel |
| SIM-09 | Intraday market data |
| SIM-10 | Liquidity + partial fills |

Until SIM-02/SIM-03, treating kernel tests as proof of live fill behavior is
wrong. Parity tests pin the kernel to today's `_should_fill` / latest-close
rules; they do not rewire `apply_fill`.
