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
| Backtester | ✅ SIM-08 (Phase 5.2) — kernel fills, shared `SimLedger`; `next_open` v1 profile, cost model and fee schedules (5.3, 5.6) |
| Shared simulated ledger | ✅ Phase 5.1 — `SimLedger` for replay and backtests, held equal to `apply_fill` |
| Experiment registry | ✅ Phase 5.4 — stored runs with a dataset fingerprint; reruns report identical / different / data changed |
| Walk-forward and sweeps | ✅ Phase 5.5 — rolling in-sample choice, out-of-sample score; capped grids |
| Backtester on the Rule DSL | ✅ A4.1 — vector-mode signals, stops (range stop in the kernel), sizing, R, baskets; three-way kernel equality test |
| Replay sessions | ✅ SIM-05 — frozen ticker/start/end, next-bar clock, server-owned 1d bars |
| Replay Lab UI | ✅ SIM-06 — launcher, blind chart, MARKET ticket, next-session, summary |
| Replay forensics | ✅ SIM-07 — episodes, MAE/MFE, buy-and-hold excess, concentration, journal |
| Blind historical replay | **Done at product surface** (SIM-06 + SIM-07 forensics) |
| Kafka `trade.executed.v1` | **Unchanged** |
| Database | Additive `simulated_executions` + `replay_sessions` / `_positions` / `_fills` / `_journals` (A4.6: `_orders`, `_drawings`, currency and fees) |
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

## Range stops and the DSL backtester (A4.1)

The DSL backtester (`services/backtest/strategy.py`, `POST
/v1/backtest/strategy`) books **every** fill through
`services/backtest/fills.py::book`: the kernel decides, the fee schedule
prices, `SimLedger` books. Entries and exit-rule / time exits are MARKET
orders on the bar after the signal under the run's profile (`next_open` by
default, `next_close` = `legacy_close`).

Protective stops are a resting order, so they are judged on the bar's
range by a separate pure kernel function,
`evaluate_range_stop(order, market, profile, costs)` (STOP_LOSS orders
only; `ineligible` otherwise):

- sell stop (protects a long): open <= stop fills at the **open** (a gap
  through the stop, flagged `gap` on the trade); else low <= stop fills at
  the stop; else not triggered;
- buy stop (protects a short): open >= stop fills at the open (gap); else
  high >= stop fills at the stop.

This is not the live rule: live STOP_LOSS stays close-only in
`evaluate_order` (see "Why same-day OHLC touches are not used"); a backtest
stop rests from its entry fill, so the bar's range after the open is fair
game. The open is always first, so a gap never fills at a price the bar did
not trade. The profile is recorded as provenance; the rule is the same under
both profiles.

**Priority within one daily bar** (`strategy.STOP_PRIORITY`): (1) a stop the
open gapped through, at the open; (2) under `next_open`, a pending exit
order at the open; (3) the price stop nearest the open (highest for a
long, lowest for a short; ties fixed, then ATR, then trailing) at its level
when the low (high) reaches it; (4) under `next_close`, a pending exit
order at the close. After a `next_open` entry the entry bar's range can
already hit the stop; after a `next_close` entry stops start the next bar.
Trailing stops ratchet after each close and apply from the next bar.

**Shorts.** `SimLedger.apply_short` (A4.1) opens (SELL, credits the proceeds
less fees, re-averages) and covers (BUY, debits cost plus fees, realises
`(avg - price) x qty`) short positions in a separate `shorts` book;
`market_value` subtracts them. A cover is never refused for cash. `apply`
(long trades, the `apply_fill` twin) is unchanged. Only the DSL backtester
shorts, only symbols a run declares shortable, only US listings.

### The three-way kernel equality test (A4's done-when)

`tests/test_kernel_three_way.py` fixes one daily bar and a set of orders
(market buy and sell, limit buy and sell, a limit buy that does not
trigger, a STOP_LOSS sell) and fills each through three production paths:
**live** (`execute_trade`, or `create_pending_order` +
`settle_pending_orders`, so `apply_fill` books it), **replay**
(`create_replay_session` + `submit_replay_order`; a limit or stop order is
placed on the first bar and judged by `advance_replay_session` on the
second, as live settles a pending order on that bar) and **backtest**
(`fills.book`). It compares fill or no fill, fill price, quantity, cash
change and (USD) realised P&L, for every fee schedule of the symbol's
currency. Since A4.2 live fills pay the ticker's default schedule (Indian
symbols: the venue's equity delivery schedule, version in force on the
fill's venue date; US: none); since A4.6 replay pays the same default
(`auto`, frozen on the session) on the bar's venue date. Under the
live default schedule the backtest's fees and cash change equal live's to
the cent; under any other schedule the backtest's cash change equals the
path's cash change before its own fees, less exactly that schedule's fees on
the same fill and date (`test_three_way_inr_default_fees` is the headline
for rupees; `test_three_way_inr_replay_equals_live` for rupee replay).

| Path / profile | `legacy_close` (= `next_close`) | `next_open` |
| --- | --- | --- |
| live, USD (`none`, `us_equity_2026`, `us_equity`) | compared | skipped: live is pinned to `legacy_close` |
| live, INR (`none`, `in_delivery_nse_2026`, `in_equity_delivery_nse` (the live default: equal to the cent), `in_delivery_bse_2026`) | compared | skipped: same |
| replay, USD | compared | skipped: replay sessions are pinned to `legacy_close` |
| replay, INR (A4.6: the session pays `in_equity_delivery_nse`, equal to the cent) | compared | skipped: replay sessions are pinned to `legacy_close` |
| backtest | compared (the reference) | its fill must equal the kernel's own decision: the open for market orders, `ineligible` for limit and stop (`test_next_open_backtest_path`) |

`test_three_way_market_buy_headline` asserts the three fills of one market
buy are equal objects. Range stops are backtest-only and are pinned by
`tests/test_range_stop.py`.

## Costs: date-versioned fee schedules (A4.2, M7.2)

`services/simulation/fees.py` holds every schedule as a typed table in code
(no database table): a **family** (`FeeSchedule`) is a list of versions
(`FeeVersion`, `effective_from` / `effective_to` inclusive), each a list of
components (`Component`: key, label, kind `value` / `per_share` / `flat` /
`gst`, rate, side, cap, GST base, per-scrip-per-day flag) and each component
names its `Source` (URL, title, the document's date, read on 26 Nov 2026).
Every rate and its source: the workspace note `docs/a4-cost-sources.md`.

- **A fill pays the version in force on its fill date**: the bar's venue
  date in backtests (`fills.book(on=...)`, the template engine's bar date),
  the venue date of the evaluation instant for live market and pending
  fills (`fee_view.fee_date`). Rates change at the venue's midnight.
- **Before the first confirmed date** (`coverage_from`, the first date every
  rate in the family is confirmed): the earliest version prices the fill
  and the breakdown says `before_coverage`; results count those fills. NSE
  families start on 1 Oct 2024 (NSE/FA/64232), BSE on 1 Dec 2022, US on
  14 May 2025 (its first version, $27.80 SEC fee, has no confirmed start).
- **Families**: `in_equity_delivery_nse` / `_bse` (aliases
  `in_delivery_nse_2026` / `in_delivery_bse_2026`), `in_equity_intraday_nse`
  / `_bse`, `in_futures_nse`, `in_options_nse` (premium-based), `us_equity`
  (alias `us_equity_2026`), `none`. BSE F&O is left out (the sources read
  disagree on the BSE options charge). STT on exercised options is not
  modelled.
- **The F&O change**: STT on futures sales 0.02% to 0.05%, options sales
  0.10% to 0.15% of premium, from 1 Apr 2026 (Finance Act 2026, NSE/FATAX/73524).
  NSE folded IPFT into the transaction charge from 1 Mar 2026 (NSE/FA/73061;
  the all-in rate did not change), so a fill before then pays
  `exchange_transaction` + `ipft` separately.
- **Brokerage**: a broker model per run, `zerodha` (delivery free; intraday
  and futures 0.03% or Rs 20 per executed order, whichever is lower; options
  Rs 20) or `zero`; `commission_bps` is added to it. GST is 18% of brokerage
  + exchange charge + SEBI fee (+ IPFT). STT rounds to the rupee per fill,
  everything else to the paisa (cent).
- **DP charge** once per scrip per day on sells (`book(dp_seen=...)`, live
  looks for an earlier sell of the scrip that venue day).
- **Default on for Indian symbols** (`services/fee_view.py`): live paper
  fills and backtests (`fee_schedule: "auto"`, the new default) use the
  venue's delivery schedule; other markets `none` (US `us_equity` stays an
  opt-in for backtests, so live US cash maths is unchanged). Replay (A4.6)
  uses the same default, resolved once when the session opens
  (`replay_sessions.fee_schedule`). Existing trades are never recalculated (`trades.fees` NULL).
- **Live ledger**: a buy pays value + fees (a non-base buy converts the
  shortfall including fees), a sell credits value - fees (refused when the
  fees exceed the value); `realized_pnl` stays the price gain and
  `TradeOut.realized_pnl_net` takes the sell's fees off; the portfolio's
  `realized_pl_net` = `realized_pl` - every fee paid (Zerodha Console's net
  realised P&L). A pending buy reserves its estimated fees too.
- **ADV participation cap** (backtests only; replay is manual one-bar
  orders): a buy (or a short) fills at most `adv_cap_pct` (default 10) % of
  the 20-day average traded value, close x volume of the 20 bars before the
  fill bar. The rest is not filled (`requested_quantity` /
  `requested_shares`, "partial: N of M shares"); zero shares is a skip
  (`adv_cap`); fewer than 20 earlier bars is not capped (`not_capped`).
  Exits are not capped; an exit over the cap reports `exit_adv_pct`.
  Runs saved before A4.2 have no `adv_cap_pct` and rerun uncapped.
- **Not checked**: price bands (circuit limits) and the T2T, ASM and F&O
  ban lists: exchange data StockViz does not hold. Indian results say so
  (`costs.price_bands_note`).
- **Results** carry `costs` (schedule, brokerage, the versions used with
  their fill counts, components and sources, fills before coverage, the
  price-band note) and `liquidity`; net figures first, gross second
  (`gross_return`, `gross_final_nav`, `total_fees`, `price_costs` on the
  template summary too).
- **Rerun honesty**: `registry.result_differences` skips the A4.2 fields a
  stored result lacks (`STAMPS_ADDED_LATER`, at any depth) and compares
  everything it holds. A stored run whose fees fall on dates where a rate
  is now date-correct reruns `different` on `summary`/`trades`/
  `equity_curve`: US runs saved with `us_equity_2026` with a sale before
  4 Apr 2026 (SEC fee $27.80 to 13 May 2025, $0 to 3 Apr 2026, where the
  old flat schedule charged $20.60), a sale in 2025 (TAF $0.000166/$8.30)
  or a sale 1 Oct-31 Dec 2026 (TAF paused). NSE runs with a fill before
  1 Mar 2026: a template run's per-trade fee list now names `ipft`
  separately (`trades` differs even where the total is the same); a rule
  strategy run differs only where the split rounding moves a paisa. BSE
  delivery runs, `none` runs, US runs with sales only from 4 Apr to 30 Sep
  2026 and NSE runs with every fill on or after 1 Mar 2026 rerun
  `identical`.

## Report card, trial ledger and the locked holdout (A4.3, M7.4)

Code: `apps/api/src/stockviz/services/backtest/report.py` (pure maths),
`report_card.py` (assembly), `regime_history.py`, `trials.py` (families,
ledger, holdout), `checks.py` (record and read). Worked example:
[`benchmarks/2026-11-26-a4-report-card.md`](./benchmarks/2026-11-26-a4-report-card.md).

**What is stored and what is not.** `report` (metrics, Sharpe statistics with
PSR(0), the Monte Carlo fan, the regime split) and `window` depend only on the
run: they are part of a saved result and of a rerun's comparison. `checks`
(trials, DSR, holdout status) are read from the ledger when a response is
built and are never stored, so a saved run reruns `identical` however many
trials or unlocks were recorded after it. `STAMPS_ADDED_LATER` adds `window`,
`report`, `pbo`, `pbo_reason` and `plateau`, so runs saved before A4.3 still
rerun `identical`.

**Metrics** (net: from the NAV after fees, spread and slippage). Daily returns
`r_t = NAV_t / NAV_{t-1} - 1`; excess `e_t = r_t - 0.05/252`. CAGR
`(NAV_end / cash)^(365.25 / calendar days) - 1`. Sortino `mean(e) /
sqrt(mean(min(e, 0)^2)) x sqrt(252)`. Calmar `CAGR / max drawdown`. Over closed
round trips (net of both legs' fees; a template's buy and sell legs are paired,
a held position is marked and counted as open): win rate `wins / closed` (P&L
> 0), payoff `mean win / |mean loss|`, profit factor `sum wins / |sum losses|`,
expectancy `mean P&L`, expectancy in R `mean R` over trades with a price stop.
Exposure: sessions holding a position at the close / sessions. Average holding:
mean calendar days entry to exit. Undefined values are null with a reason.

**Sharpe statistics.** SR per day = mean / sample std of `e`; skewness and
kurtosis (not excess) from population moments; T = number of returns.
PSR(SR*) = `Phi((SR - SR*) sqrt(T - 1) / sqrt(1 - g3 SR + (g4 - 1)/4 SR^2))`
(Bailey and López de Prado 2012), SR* = 0. DSR = PSR(SR0) with
`SR0 = sqrt(V) ((1 - gamma) inv_Phi(1 - 1/N) + gamma inv_Phi(1 - 1/(N e)))`
(Bailey and López de Prado 2014), N the family's distinct variants in the
ledger and V the sample variance of their per-day Sharpes; N = 1 or V = 0
gives SR0 = 0, so DSR = PSR(0).

**The trial ledger** (`backtest_trials`, migration `e5a7c9b1d324`). A row per
(caller, strategy hash, data fingerprint): the public endpoints (`source`
`run`), saved runs (`saved`), each setting of a sweep (`sweep`) or
walk-forward (`walk_forward`, its Sharpe the mean per-day Sharpe over its
in-sample fits). A repeat bumps `runs`. Template hash: SHA-256 of the whole
request; rule strategies: their `strategy_hash` (which adds `holdout` only
when it is not `none`). Family: template type + ticker; or the rules'
canonical text with numbers as `#`, the stop kinds, the sizing kind, the
direction and the tickers. Dates, costs, cash and fill rule are not part of a
family. Anonymous runs: `user_id` NULL, one pool; no address or cookie is
stored. `stockviz.cli prune-trials [--days 365]` deletes rows not run since;
nothing schedules it.

**The locked holdout.** `holdout: last_20pct` (default on `BacktestIn` and
`StrategyBacktestIn`): the run uses the first `total_days * 4 // 5` calendar
days of the range; sweeps and walk-forwards load bars for that range only (a
test rewrites every held-out bar and finds the study's fingerprint and result
unchanged). `POST /v1/backtest/holdout/unlock` (authed) records a family's
unlock once (`holdout_unlocks`, unique per user and family; 409 the second
time, 400 without a holdout); from then on every run of the family returns
`checks.holdout.status = seen` with the holdout's result: the same request run
on `[holdout_from, to]` with `holdout: none` (warm-up from the bars before).
`holdout: none` runs the whole range and says so. Stored requests without the
field rerun with `none` (`registry.as_saved`).

**Monte Carlo fan.** `risk.engine.stationary_indices` (the Phase 8 stationary
bootstrap, shared with the portfolio Monte Carlo, whose numbers are
unchanged) resamples the run's daily net returns: 2,000 paths, mean block 5,
as many sessions as the run, seed 20261126 (in the result). Per path the
maximum drawdown; per sampled date the 5th/50th/95th NAV percentiles. Needs
20 returns.

**Regime split.** Each session gets A3.5's `REGIME_RULES` evaluated on data
stored on or before it: the index (`^GSPC` US, `^NSEI` India, by the first
ticker's market) close, 200-session SMA and 20-session volatility percentile
over its last 1,260 values (252 needed); breadth recomputed in one SQL
window query from stored daily bars of the market's active non-index symbols
(close above the mean of its last 200 closes; at least 5 judged, else
unknown). A day's return counts under the state at the previous close. The
member list is today's (survivorship-biased like the pinned universe); with
no index bars every day is "not enough data" (as on `stockviz_e2e`).

**PBO and plateaus (sweeps).** CSCV over the settings' daily net returns
(same dates): 16 blocks of `T // 16` sessions (the oldest `T mod 16`
dropped; at least 4 a block), all C(16, 8) = 12,870 splits; the in-sample
best by per-day Sharpe (ties: first) is ranked out of sample (ties averaged,
Sharpes rounded to 10 decimals), `w = rank / (N + 1)`, `logit = ln(w / (1 -
w))`, PBO = share of logits <= 0 (Bailey, Borwein, López de Prado and Zhu
2017). The plateau heatmap (net Sharpe and net return) puts the template's
two parameters on the axes; a neighbour (adjacent cell run) holds up within
25% of the best's magnitude, and fewer than half holding up is an isolated
peak.

## Cross-sectional rotation (A4.4)

`POST /v1/backtest/rotation` (`services/backtest/rotation.py`, pure;
`rotation_run.py` loads the data). Every fill goes through `fills.book`, the
same kernel and `SimLedger` path as rule strategies, with A4.2's dated fee
schedules and ADV cap.

- **Rebalance sessions** (`rebalance_signals`): the last session of each ISO
  week (Monday to Sunday) or calendar month on the venue calendar
  (`markets/calendar.py::is_session`, so a Good Friday week ends on Thursday
  and a month ending on a weekend or holiday ends on its last session), for
  every period that ends inside the window, plus the last session before the
  window (the first ranking, so the run is invested from its first session).
  A period still running at the window's end does not rebalance.
- **No look-ahead.** The ranking is the expression's vector-mode value at the
  rebalance session's close (conformance-proven equal to point mode). Orders
  fill on each symbol's next bar under the fill profile (`next_open`: its
  open). A symbol with no bar on the rebalance session, or an unknown value,
  is not ranked and is listed with the reason. A test perturbs every bar after
  a rebalance and finds that rebalance's ranks and holdings unchanged.
- **Targets.** Top N by value (ties: ticker order), with an optional buffer
  (a holding stays while its rank is at most N + buffer). Weights: 1/N of the
  equity at the rebalance close each (fewer ranked names leave cash), or
  inverse volatility (1 / the standard deviation of the last 63 daily
  returns, scaled to k/N for k names). Each rebalance resizes to the targets:
  sells first (leavers in full, trims of names over their target), then buys
  (entrants and top-ups, largest weight first), in whole shares at the fill
  bar's expected price, capped by free cash and the ADV cap. A trim is a
  `resize` round trip at the holding's average price.
- **Cash filter.** A condition judged on the market index's own bars
  (`^GSPC`, `^NSEI`; `index_close` is the index's close), at the newest index
  bar at most 5 sessions before the rebalance session. Met: sell everything
  and hold cash. Unknown: it does not act (counted). It may read prices only.
- **Turnover** per rebalance = (bought + sold) / 2 / equity at the rebalance
  close; the summary gives the mean, the total and the total per year.
- Identity: `strategy_hash` over the ranking and filter hashes, N, schedule,
  weighting, buffer, tickers, dates and costs; `data_fingerprint` over every
  bar and index close read. Saved runs (`kind` `rotation`) rerun `identical`.

## Intraday strategy backtests (A6.4, M4.5 intraday)

`POST /v1/backtest/strategy` takes `timeframe` (`daily` default, `1m` ...
`60m`), `feed` (`auto`: the best stored) and `flatten_at_close`. `from` and
`to` stay session dates. One symbol's intraday bars come from
`services/bars/intraday.py` (closed bars only), signals from the rules'
vector mode on those bars (A6.4's DSL), fills through the same kernel path
(`fills.book`) as daily runs. The engine (`backtest/strategy.py`) treats an
intraday symbol (`SymbolInput.sessions`) by these rules:

- **Signals on the bar's close, fills on the next bar** (`next_open`: its
  open; `next_close`: its close).
- **Entries only inside a session.** An entry signal on a session's last
  bar is dropped (`skip_reasons.session_end`), so an entry never fills
  across a night, weekend or holiday.
- **Holding overnight is allowed (default).** An exit signalled on a
  session's last bar fills at the next session's first bar; a stop the open
  gapped through fills there at the open (`gap`).
- **`flatten_at_close`**: a position still open at a session's last bar is
  sold at that bar's close (the kernel's `legacy_close` on that bar),
  reason `session_close` (marker "C").
- **Costs.** Each fill pays the schedule version in force on its **session
  date**. Indian symbols default to NSE/BSE delivery; a round trip closed in
  its entry's session pays the **intraday** schedule on both legs (the
  entry's delivery fee is re-priced and the difference returned to cash;
  `same_day: true` on the trade). US symbols pay the US schedule as on daily
  runs.
- **ADV cap** uses the 20-session average traded value from **daily**
  `price_bars` before the bar's session, never the intraday bars' volume
  (the owner's minute files' volume may not be exchange volume). Without 20
  daily bars an entry is not capped and is counted (`liquidity.not_capped`).
- **Annualisation.** One equity point per bar; Sharpe and Sortino are
  annualised by the venue's bars a year: bars in a regular session (NSE 375
  minutes, XNYS 390, the last bar clipped, so rounded up) x 252
  (`periods_per_year`: NSE 5m = 18,900, 60m = 1,764). CAGR uses calendar
  time; average holding is fractional days. The regime split reads, for each
  bar, the regime of the day before its session.
- **Holdout, ledger and identity** as daily runs: `from`/`to` split by date,
  every run recorded. The strategy hash adds `timeframe`, `feed` and
  `flatten_at_close` only for intraday runs; the fingerprint hashes every
  intraday bar read (open instant, OHLCV, source), the daily bars, benchmark,
  facts, news and the daily ADV.
- **Output.** Trades carry `entry_at`/`exit_at` (bar opens, UTC) beside
  session dates and `same_day`; equity points carry `at`; the result carries
  `timeframe`, `feed`, `feed_badge`, `flatten_at_close` and
  `periods_per_year`. The web shows the trades on the intraday chart in the
  venue's zone.

Tests: `apps/api/tests/test_a64_intraday.py` (next-bar fills, entries
dropped at a session's end, exits across a night, same-day fees by hand,
flatten, annualisation, daily ADV).

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
needs at least two 1d bars. Since A4.6 any currency is allowed: the book is in
the symbol's currency (`replay_sessions.currency`), so no FX is needed.

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

**Replay in the journal (A5.5).** Each forensics episode of a replay session
is also a journal entry (`/v1/journal/entries?source=replay`), grouped by
the same flat-to-flat rule. Its MAE and MFE use forensics' close rule and
numbers (`exact_close`); the session's plan pairs with the first episode,
and R needs the plan's stop (a replay journal without one has no R). News at
entry and exit and the entry page's bars never pass the session's clock, and
anonymised drills not yet revealed are left out of the journal.


**Trade plans (A5.4, M10.3).** Since migration `b5d4a7e1c902` the replay
journal and the drill plan are one row in `trade_plans` (`source` `replay`
or `drill`, keyed on the session: `replay_session_id` unique). The journal's
thesis is `thesis_text`, expected bars `horizon_bars`, reflection `notes`;
the drill plan's note is `why`. `drill_plans` and `replay_journals` are
archived in the `archive` schema with their rows (dropping them is a later
batch). The routes and their shapes are unchanged; `ReplayJournalOut` adds
`written_after_entry`. The lock rule is A4.7's: a plan that existed before
the session's first fill locks at it (`locked_at` = the fill's simulated
`evaluated_at`); a journal started after the first fill is **written after
entry**: frozen the same way, never "locked". A session that completes or
is cancelled closes an active plan and cancels an unfilled one. The
migration test (`tests/test_trade_plans_migration.py`) plays drills and
replays, downgrades, adds old-style rows and checks every drill score, the
deck summary and replay forensics are identical after the copy.

**Replay in any currency, the lag, the chart and resting orders (A4.6, M9.1,
M9.2).**

- **Currency and cash.** A session takes its symbol's currency and starts
  with `starting_cash` in it; omitted, $100,000 (USD), ₹10,00,000 (INR, ten
  lakh) or 100,000 units of another currency (`DEFAULT_CASH_BY_CURRENCY`).
  Every amount the replay routes return is in `currency`.
- **Fees.** The A4.2 default resolver (`auto`, frozen at creation): NSE and
  BSE symbols pay their equity delivery schedule, the version in force on
  the bar's venue date, the Zerodha brokerage model and DP once per scrip per
  day (the first sell at that bar); other venues `none`. Cash moves net,
  `ReplayFill.fees`/`fee_lines` record them, `realized_pnl` stays the price
  gain, the summary adds `fees_paid` and forensics nets episode P&L of fees.
- **Indices** (`^NSEI`, `^GSPC`) can be replayed to watch, study and draw on,
  not traded (400, `ReplayNotTradable`).
- **The 30-day lag.** An XNSE or XBOM session must end at least
  `REPLAY_MIN_LAG_DAYS` (default 30; 0 is off) calendar days before today on
  the venue (SEBI's rule for simulated trading on recent prices): the
  resolved end bar's date must be on or before that cut-off, else 400 with
  the latest allowed date. The owner-only override is server configuration,
  `REPLAY_LAG_OVERRIDE_USER_IDS` (user ids, comma separated, empty by
  default); no request field relaxes it, and `lag_override` records a waived
  session. `GET .../availability` returns `lag_days` and `max_end`. There is no
  prize or leaderboard anywhere (a test greps replay's code).
- **Indicators** (`GET .../indicators?names=`) run the registry on the
  visible bars (`start_at` to `current_at`) warmed up on the stored bars
  before `start_at`, with index closes cut at `current_at` for the RS line;
  nothing after the clock is read, and a value equals the live route's with
  its window cut at the clock (tested at every step with future bars stored).
- **Events** (`GET .../events`): Aegis news linked to the symbol with
  `available_at <= current_at` (the bar's timestamp: conservative, a headline
  published during a session shows from the next bar) and the session's own
  fills. Earnings, dividends and splits are left out (their figures can be
  later than the clock). The live events route is never called from replay.
- **Drawings** (`/sessions/{id}/drawings`, CRUD like A3.2): their own table,
  `replay_drawings`, so the live chart, `drawing()` rules and other sessions
  never see them and the session never sees live ones (a live drawing could
  sit on a later date). Anchors between the first bar and the clock; the
  anchored VWAP is refused (its line reads every stored bar).
- **Resting orders.** `POST .../orders` with `limit` (buy or sell),
  `stop_loss` or `take_profit` (sell only) and `limit_price` places a
  `replay_orders` row at the clock; it is first judged on the next bar (the
  trader saw this bar's close, which a market order takes). Every advance
  runs each open order, oldest first, through `evaluate_order` with the
  session's profile (`legacy_close`: triggers on that close, fills at it).
  Nothing is reserved: placement checks the cash at the limit (buy) or the
  shares (sell), and a fill the book cannot pay or deliver is `rejected` with
  the reason. `POST .../orders/{id}/cancel`; completing the session expires
  open orders, cancelling it cancels them; at most 20 open.

**Not in SIM-06 / SIM-07 / A4.6.** Intraday, rewind, branching, dataset version
snapshots, spreads/slippage, variable autoplay (A6), reservations for resting
orders.
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
- `POST /v1/replay/sessions/{id}/orders` — intent only; a market order fills at
  the current close, a limit / stop order rests (A4.6)
- `GET /v1/replay/sessions/{id}/orders`, `POST .../orders/{order_id}/cancel` (A4.6)
- `GET /v1/replay/sessions/{id}/indicators?names=`, `GET .../events` (A4.6)
- `GET`/`POST /v1/replay/sessions/{id}/drawings`, `PATCH`/`DELETE .../drawings/{id}` (A4.6)
- `POST /v1/replay/sessions/{id}/cancel`
- UI: `/replay`, `/replay/{id}`, `/replay/{id}?view=forensics`

Live `evaluation_clock()` remains wall-clock UTC for paper trading.

## Drills and decks (A4.7, M9.3)

A **deck** is K replays seeded from a rule's real historical triggers; a
**drill** is one of them. Tables `drill_decks`, `drills`, `drill_plans`
(migration `53b66a2e2ec2`); code `services/drills/`, routes `/v1/drills`.

- **Triggers.** The rule (a setup version, or inline text saved as a
  version of the user's "Rules from drills" setup) is evaluated in vector
  mode on every symbol of the universe (tickers, a watchlist, or a market,
  as the scan event study takes them). A trigger is a false-to-true edge,
  found by `checklist/evidence.py::edge_indices`, the same code the scan
  event study counts events with: true on the bar, false on the bar
  before; a bar after an unknown one is not a trigger; no cooldown. The
  range defaults to the last ten years to the latest completed session.
  **Acceptance** (`tests/test_drills.py::test_acceptance_deck_triggers_equal_the_vector_edges`):
  with K at least the number of triggers, the deck's (ticker, date) set
  equals the vector series' false-to-true dates computed independently in
  the test (and the scan event study's `events_found`); with K below it,
  the deck is an exact subset.
- **Sessions.** Each drill is a replay session (A4.6: the symbol's currency,
  its fees, resting orders) starting N stored bars before the trigger
  (default 60) and ending M after it (default 40), both clamped to the
  stored bars. It opens at the trigger bar (`current_at` = the trigger),
  with the lead-in visible and nothing after it.
- **Lag.** A trigger on an NSE/BSE symbol whose session would end inside the
  30-day lag is skipped and counted (`lag_skipped`), unless the owner's
  override lists the user. `triggers_found` counts every edge,
  `triggers_eligible` those left.
- **Sampling.** The eligible triggers, sorted by (date, ticker), are drawn
  with `random.Random(seed).sample(eligible, K)`; the seed (given, or drawn
  and stored) makes the deck reproducible. Drills keep the drawn order, so
  positions do not reveal chronology.
- **Anonymised by default** (design note question 5). While a drill is not
  revealed, every `/v1/drills` response passes through
  `anonymise.Mask`: the ticker is "Stock A", "Stock B"... by position in the
  deck (a repeat of a symbol gets a new letter); the company name and the
  ticker are replaced in free text (error messages); every date and
  timestamp, and every ISO date inside a string, moves by
  `date_offset_weeks` (52 to 520 whole weeks, earlier or later, never past
  today), so weekdays are the real ones; prices, volumes and returns are
  unchanged. Holidays are not remapped, so a real holiday's gap can sit on
  an ordinary shown date. News markers keep only their count per day:
  headlines, sources and links name the company. `/v1/replay` answers 404
  for an anonymised drill's session (forensics, history, events, all of
  it) and leaves drill sessions out of its list; drawings and the
  `expected_current_at` of a step are translated back to real dates by the
  API. The deck's own universe and date range are the caller's input and
  are shown as given (a short ticker list narrows the guess; a market or a
  watchlist does not). A deck can turn anonymisation off.
- **Plan and score (process, not profit).** Before the first order the
  drill asks for a plan: planned entry, stop and size, long
  (since A5.4 a `trade_plans` row with `source = 'drill'`, keyed on the
  replay session; A4.7's `drill_plans` is archived). Orders without a plan
  are 409; the plan locks at the first fill.
  After the reveal the score checks: entry (the first buy within 2% of the
  plan), stop (no bar closed at or below the stop with shares still held
  after that bar's fills; fills are at the close, so a resting stop-loss at
  the plan's price or a sell on that bar exits in time; never reached while
  holding is not applicable), size (most shares held at most the plan).
  Score = checks passed of those that apply; no trade scores nothing. R
  achieved (total P&L net of fees over (average buy - stop) x peak shares)
  is shown beside it and is not the score. No leaderboard, prize or
  ranking.
- **Reveal** (`POST /v1/drills/{id}/reveal`): ends a running session
  (cancelled: read-only), then shows the ticker, company, sector, the real
  trigger and session dates, the shown trigger date and the offset, the
  return from the trigger's close 5, 20 and 60 bars later and the stored
  bars after the session, and the score. Revealed, the replay routes serve
  the session again.

Routes (authed): `POST`/`GET /v1/drills/decks`, `GET`/`DELETE
/v1/drills/decks/{id}` (the delete removes drills, plans and their replay
sessions), `GET /v1/drills/{id}`, `PUT .../plan`, `POST .../orders`,
`POST .../orders/{order_id}/cancel`, `POST .../advance`, `GET
.../indicators`, `GET .../events`, `GET`/`POST .../drawings`,
`PATCH`/`DELETE .../drawings/{id}`, `POST .../reveal`. UI: `/drills`,
`/drills/new`, `/drills/{id}`. Tests: `test_drills.py` (the acceptance,
sampling by seed, lag skip, a leak check that greps every anonymised
response for the ticker, the company and each real date of the session,
weekday-preserving shift, plan and score rules, reveal, delete, isolation),
`test_drills_migration.py` (PostgreSQL up/down/up).

## Later program

| ID | Scope |
| --- | --- |
| SIM-02 | **Done.** Live MARKET fills call `evaluate_order(..., LEGACY_CLOSE)`; `apply_fill` is unchanged |
| SIM-03 | **Done.** Live pending LIMIT / STOP_LOSS / TAKE_PROFIT settlement uses the same kernel; `_should_fill` is gone from production |
| SIM-04 | **Done.** Versioned profile registry + durable `SimulatedExecution` provenance |
| SIM-05 | **Done.** ReplaySession with frozen ticker/start/end, next-bar clock, server-owned 1d bars |
| SIM-06 | **Done.** Blind historical Replay Lab UI |
| SIM-07 | **Done.** Post-trade forensic analytics + decision journal |
| SIM-08 | **Done** (Phase 5.2). Backtester uses the same execution kernel and the shared `SimLedger` |
| SIM-09 | Intraday market data |
| SIM-10 | Liquidity + partial fills |

Kernel unit tests pin `legacy_close` itself. Live MARKET tests live in
`test_market_kernel_integration.py`. Live pending tests live in
`test_pending_kernel_integration.py`. Provenance tests live in
`test_execution_provenance.py`. Replay session tests live in
`test_replay_session.py`. Forensics tests live in
`test_replay_forensics.py` and `test_replay_forensics_router.py`. Phase 5:
`test_sim_ledger.py` (ledger parity with `apply_fill`),
`test_backtest_window.py` (warm-up, currency, basis), `test_cost_models.py`,
`test_india_fees.py`, `test_dated_fees.py` (A4.2), `test_experiment_registry.py` (identical reruns) and
`test_walk_forward.py`. A4.1: `test_range_stop.py` (range stop, shorts
ledger), `test_strategy_engine.py` (stops, priority, sizing, R, baskets,
unknown signals, warm-up, no look-ahead), `test_strategy_backtest.py` (the
route, watchlists, shorts refused, rerun identical) and
`test_kernel_three_way.py`.
