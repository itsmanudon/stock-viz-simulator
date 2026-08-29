# Simulation execution kernel

SIM-01 introduces a **pure, deterministic execution engine**: given an order
intent, an observable market snapshot, and an execution profile, should this
order fill, at what price, and why?

**All live equity paper-order execution decisions** (MARKET, LIMIT, STOP_LOSS,
TAKE_PROFIT) go through `evaluate_order(..., LIVE_PAPER_EXECUTION_PROFILE)`
where that constant is canonical `LEGACY_CLOSE`. Accounting still mutates
only in `apply_fill`. Successful fills persist a `SimulatedExecution` row
from the same `FillDecision`. Execution realism has **not** improved: the
profile is still close-only `legacy_close`, and pending settlement still
runs on the weekday EOD schedule.

## Status

| Layer | Status |
| --- | --- |
| Pure kernel (`apps/api/src/stockviz/services/simulation`) | ✅ SIM-01 |
| Live `execute_trade` / **MARKET** fills | ✅ SIM-02 — `evaluate_order(..., LEGACY_CLOSE)` |
| Live pending-order settlement | ✅ SIM-03 — LIMIT / STOP_LOSS / TAKE_PROFIT via the same kernel |
| Versioned profile registry | ✅ SIM-04 — `get_execution_profile(name, version)` |
| Durable execution provenance | ✅ SIM-04 — `simulated_executions` (fill-only, no backfill) |
| Backtester | **Unchanged** — separate engine (SIM-08) |
| Replay sessions | ✅ SIM-05 — frozen ticker/start/end, next-bar clock, server-owned 1d bars |
| Replay Lab UI | ✅ SIM-06 — launcher, blind chart, MARKET ticket, next-session, summary |
| Replay forensics | ✅ SIM-07 — episodes, MAE/MFE, buy-and-hold excess, concentration, journal |
| Blind historical replay | **Done at product surface** (SIM-06 + SIM-07 forensics) |
| Kafka `trade.executed.v1` | **Unchanged** |
| Database | Additive `simulated_executions` + `replay_sessions` / `_positions` / `_fills` / `_journals` |
| API | Additive execution provenance + `/v1/replay/*`; `TradeOut` unchanged |
| Frontend | Replay Lab at `/replay` (SIM-06) with forensics/journal (SIM-07); live Trade/Portfolio unchanged |

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

### Live MARKET adapter (SIM-02)

`PriceBar.ts` remains the bar's market/session timestamp. It is **not** copied
into `MarketSnapshot.observed_at`.

The stored 1d close is already the paper-trading quote at order time. The
adapter therefore sets both `OrderIntent.submitted_at` and
`MarketSnapshot.observed_at` to the same aware UTC evaluation instant. That
does not rewrite historical bar chronology; it states that this close is
allowed to influence **this** live ticket.

Using `bar.ts` as `observed_at` would be wrong: a naive midnight bar can be
strictly before `submitted_at`, and the kernel would refuse a fill that
today's paper path must still complete.

### Live pending adapter (SIM-03)

Pending LIMIT / STOP_LOSS / TAKE_PROFIT orders exist across time. The adapter
therefore:

- Sets `OrderIntent.submitted_at` to the persisted `PendingOrder.created_at`,
  normalized to aware UTC. StockViz stores naive UTC (`stockviz._time.utcnow`);
  naive values are labeled UTC at the adapter boundary. Local-timezone
  invention is not performed.
- Sets `MarketSnapshot.observed_at` to the **settlement evaluation instant**,
  not `PriceBar.ts`.

`PriceBar.ts` remains the market/session timestamp. `observed_at` is when
that stored daily close is considered available to the simulator. Ingest
does not persist a separate availability timestamp, so settlement time is
the deterministic availability instant: the 16:45 ET job runs after the
16:30 daily refresh, and a stored close is known when settlement evaluates it.

The trading layer still refuses a stale calendar session **before** building
`MarketSnapshot` / `OrderIntent`. A prior-day close that numerically crosses
a limit does not reach the kernel when `session_date` is today.

A kernel `INELIGIBLE` result (ticker mismatch, snapshot earlier than
submission, unsupported BUY stop/take-profit, malformed adapter state) is
logged with order id / ticker / type / side / reason and the row is left
**pending**. That is adapter/domain inconsistency, not an account failure.
Insufficient cash/shares/FX still cancel in the trading layer after a
`FILLED` decision.

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

The only implemented profile. The canonical object is `LEGACY_CLOSE`
(`name = "legacy_close"`, `model_version = "v1"`, plus a fixed assumption
tuple). Recognition is dataclass equality against that object, not name and
version alone. A profile that reuses the name/version with different
assumptions is **not** `legacy_close` and returns `INELIGIBLE`.

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

Unknown or non-canonical profiles return `INELIGIBLE`. They do not silently
fall back to `legacy_close`, and they cannot attach custom assumptions to a
legacy fill. A genuine `legacy_close` decision always traces the canonical
assumption tuple.

## Current EOD limitations

Live paper trading still:

- Fills market orders at the **latest stored 1d close**
- Settles pending limit/stop/take-profit once per weekday after the daily
  refresh, at that session's close, not at the trigger
- Has no bid/ask, last trade, or order book
- Does not model latency, commissions, or liquidity
- Uses a simulated SSE quote that is **not** a fill source

Those limitations remain after SIM-06. Replay Lab adds a **frozen 1d
historical clock**, an isolated book, and a future-blind UI; it does not add
spreads, slippage, OHLC-touch fills, partial fills, rewind, or intraday
replay. See [KNOWN_LIMITATIONS.md](./KNOWN_LIMITATIONS.md).

## Why same-day OHLC touches are not used

A tempting "improvement" for limits is:

- BUY LIMIT triggers when `low <= limit`
- SELL LIMIT triggers when `high >= limit`

That is **incorrect** for live paper orders against a daily bar.

If a user submits a buy limit at 14:00 and the daily low printed at 11:00,
the daily OHLC cannot prove the touch happened after submission. Using the
full-day high/low would create impossible pre-submission fills.

`legacy_close` therefore uses **close-only** comparison, matching the
historical pending-order EOD rules. Future replay/backtest profiles may use
**next-bar** OHLC under explicit, documented assumptions. They must not
silently replace live EOD settlement.

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

Do not add stub classes that pretend these work. They are not registered in
`get_execution_profile`. Unknown name/version pairs fail explicitly; there is
no silent fallback to `legacy_close`.

## Simulation Truth Layer

Every successful live equity paper fill now has two related records:

1. **Ledger** — `trades` (cash/position economics via `apply_fill`)
2. **Provenance** — `simulated_executions` (how the simulator priced that fill)

They commit in the same transaction as the outbox `trade.executed.v1` row.
Provenance is **not** copied onto the Kafka v1 payload.

```text
Observed:
  stored OHLCV snapshot
  market interval (currently 1d)
  evaluated_at (adapter evaluation instant, not PriceBar.ts)

Modelled:
  execution profile + model version
  snapshotted assumptions
  fill decision (reason, reference_price, fill_price)
```

Current `legacy_close` v1:

| Field | Value |
| --- | --- |
| Reference close | stored 1d close |
| Model adjustment | none |
| Simulated fill | the same close |
| Profile | `legacy_close` v1 |
| Granularity | 1d |

Future Retail Realistic (unimplemented):

| Field | Value |
| --- | --- |
| Reference price | X |
| Spread | modelled |
| Slippage | modelled |
| Simulated fill | Y ≠ X |

`reference_price` and `fill_price` are stored separately so that future
profiles do not need a schema change when they diverge.

Provenance is recorded only for **successful fills**. NOT_TRIGGERED,
INELIGIBLE, and account-layer cancellations do not get a row. Trades written
before SIM-04 have none; `GET /v1/trades/{id}/execution` returns 404.

`evaluated_at` is when the trading adapter asked the kernel.
`created_at` is when the provenance row was persisted. They are not the same
column.

Live paper always uses `LIVE_PAPER_EXECUTION_PROFILE` (`legacy_close` v1).
There is no user-facing profile selector.

## ReplaySession + simulation clock

SIM-05 is a **server-authoritative** historical replay book. It is not the
live `Portfolio`, and callers do not supply OHLC.

```text
ReplaySession
    ticker (pinned, one symbol)
    start_at / current_at / end_at  (stored 1d PriceBar.ts, frozen at create)
    pinned profile + version (legacy_close v1)
    isolated cash / positions

SimulationClock(now=current_at)
    → never reads the wall clock
    → time only moves forward, one stored bar per advance

GET market / history
    → PriceBar rows where start_at <= ts <= current_at (<= end_at)
    → never bars after current_at

POST advance
    → next stored 1d bar
    → completes when that bar is the last in the frozen range

POST orders (intent only)
    → MarketSnapshot from the current stored bar
    → evaluate_order(session profile)
    → ReplayFill on FILLED (no Trade / SimulatedExecution / Kafka)
```

**Range snapping.** `start_at` becomes the first stored 1d bar at-or-after the
request. `end_at` becomes the last stored 1d bar at-or-before the request, or
the latest stored 1d bar at creation if omitted. The resolved timestamps are
persisted; ingesting a later bar does not extend the session. A usable range
needs at least two 1d bars. Non-USD symbols are rejected (no historical FX).

**Current bar.** `current_at` is the `PriceBar.ts` of the currently observable
stored daily bar. That bar and earlier bars in `[start_at, current_at]` are
visible. The next stored bar is not. Kernel `observed_at` / order
`submitted_at` are that timestamp labeled UTC. Bar N cannot fill until replay
has advanced to N. Stored 1d rows may include calendar days when the dataset
contains them; Replay does not skip weekends or holidays unless those dates
have no stored bar.

**Statuses.** `active` → `completed` when advance lands on `end_at` (no next
bar). Manual `POST .../cancel` → `cancelled`. Advance or orders on a terminal
session return 409. Sessions are not deleted; child rows cascade if a session
row is removed.

**Replay Lab (SIM-06).** `/replay` launches a session. `/replay/{id}` is the
workspace: server-visible history chart, MARKET ticket, next-session control,
isolated cash/position/fills, and a computed summary marked at the current
replay close. The UI never fetches generic bars, live quotes, or SSE.

**Replay forensics (SIM-07).** `GET /v1/replay/sessions/{id}/forensics`
reconstructs long-only **episodes** from `ReplayFill` chronology
(`evaluated_at`, then fill id). Partial sells stay in one episode; a full
exit then a new buy starts another. Analytics use only bars already visible
at `current_at` (cancelled the same; completed through frozen `end_at`).
Derived MAE/MFE/benchmark/concentration are computed, not stored.

MAE/MFE are **daily-bar** range statistics, not tick excursion and not
execution timestamps. After each bar's fills, if quantity is still open,
compare that bar's stored low/high against the **active weighted entry**
(buy-notional / buy-quantity):

* `MAE_pct` = worst `(low - entry) / entry * 100`
* `MFE_pct` = best `(high - entry) / entry * 100`

A dedicated exit bar does not contribute same-day high/low once quantity is
zero. Holding is reported as **bars held** plus **calendar duration**, not
"trading days" — stored 1d rows may include calendar days.

Session benchmark is percentage-only: start-bar close → analysis-bar close
versus replay equity return on starting cash. Excess = replay return % −
buy-and-hold %. No assumed 100% capital deployment in dollars. Concentration
is `position_notional / replay_equity` at fills (one-ticker replay
exposure, not portfolio diversification). Optional session max drawdown
walks visible closes, applying fills at actual fill prices.

`ReplayJournal` is 1:1 with the session. Thesis, invalidation, expected
holding bars, and confidence (1–5) may be edited until the first fill;
then they lock (`409 ReplayJournalLocked`). Reflection stays editable.
There is no R-multiple: Replay does not store a stop/invalidation *price*.
No retrospective LLM and no buy/sell advice.

**Not in SIM-06 / SIM-07.** Intraday, rewind, branching, dataset version
snapshots, spreads/slippage, historical FX, pending replay orders.
Historical bar *corrections* can still change observations; the horizon is
frozen, the row contents are not.

Authed API and Replay Lab UI:

- `POST /v1/replay/sessions` — `ticker`, `start_at`, optional `end_at` / cash
- `GET /v1/replay/availability` — stored 1d range for a ticker
- `POST /v1/replay/sessions/{id}/advance` — next stored bar
- `GET /v1/replay/sessions/{id}/market` — current server bar
- `GET /v1/replay/sessions/{id}/history` — visible bars through `current_at`
- `GET /v1/replay/sessions/{id}/summary` — cash/equity/PnL at current close
- `GET /v1/replay/sessions/{id}/forensics` — episodes, MAE/MFE, benchmark, concentration
- `GET` / `PUT /v1/replay/sessions/{id}/journal` — thesis (locks after first fill)
- `POST /v1/replay/sessions/{id}/orders` — intent only; fill at current close
- `POST /v1/replay/sessions/{id}/cancel`
- UI: `/replay`, `/replay/{id}`, `/replay/{id}?view=forensics`

Live `evaluation_clock()` remains wall-clock UTC for paper trading.

## Later program

| ID | Scope |
| --- | --- |
| SIM-02 | **Done.** Live MARKET fills call `evaluate_order(..., LEGACY_CLOSE)`; `apply_fill` is unchanged |
| SIM-03 | **Done.** Live pending LIMIT / STOP_LOSS / TAKE_PROFIT settlement uses the same kernel; `_should_fill` is gone from production |
| SIM-04 | **Done.** Versioned profile registry + durable `SimulatedExecution` provenance |
| SIM-05 | **Done.** ReplaySession with frozen ticker/start/end, next-bar clock, server-owned 1d bars |
| SIM-06 | **Done.** Blind historical Replay Lab UI |
| SIM-07 | **Done.** Post-trade forensic analytics + decision journal |
| SIM-08 | Backtester uses the same execution kernel |
| SIM-08 | Backtester uses the same execution kernel |
| SIM-09 | Intraday market data |
| SIM-10 | Liquidity + partial fills |

Kernel unit tests pin `legacy_close` itself. Live MARKET tests live in
`test_market_kernel_integration.py`. Live pending tests live in
`test_pending_kernel_integration.py`. Provenance tests live in
`test_execution_provenance.py`. Replay session tests live in
`test_replay_session.py`. Forensics tests live in
`test_replay_forensics.py` and `test_replay_forensics_router.py`. The backtester is still a separate engine.
