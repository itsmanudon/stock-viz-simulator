# Rule DSL

One rule language for screens, alerts and saved setups (A2.1, feature
M4.1). A rule is a condition judged on each daily bar of a symbol: **met**,
**not met** or **unknown** (some data it needs is missing). The code lives
in `apps/api/src/stockviz/services/dsl/`; the agent notes are under "Rule
DSL (A2.1)" in `apps/api/CLAUDE.md`.

## Examples

```
close > sma(close, 200) and sma(close, 50) > sma(close, 200)
weekly.close crosses_above weekly.ema(close, 10)
rsi(14) < 30 and volume > 2 * sma(volume, 20)
close >= highest(high, 252)[1] and pct_change(close, 5) > 0
macd().signal crosses_below macd() or close < bb(20, 2).lower
fundamental.pe < 25 and fundamental.roe > 15
delivery_pct > 60 and close > open
news.count(7, sentiment="negative") = 0
rs(126) > 0 and bars_since(close crosses_above sma(close, 50)) <= 5
```

## The language

| Part | Form |
| --- | --- |
| Bar series | `open high low close volume`; `delivery_pct deliverable_qty` (NSE, daily only); `index_close`, the venue index's close (A2.4) |
| Arithmetic | `+ - * /` and unary `-`; division by zero is unknown |
| Comparison | `< <= > >= = !=` (`==` also means `=`). One per condition: write `a < b and b < c` |
| Logic | `and`, `or`, `not`, parentheses |
| Crossing | `a crosses_above b`: above now, at or below on the bar before (`crosses_below` mirrors it) |
| Offset | `x[n]`: `x` n bars ago, on `x`'s own timeframe (`weekly.close[1]` is last week's close) |
| Timeframe | `weekly.x`, `monthly.x`, `weekly.(close > open)` |
| Fundamentals | `fundamental.<metric>` |
| News | `news.count(days, sentiment="...", event_type="...")` |
| Comments | `# to the end of the line` |

`index_close` is the close of the listing's market index on each bar's date:
`^GSPC` for US listings, `^NSEI` for Indian ones, forward-filled at most 5
bars (the series `rs()` reads). A bar never sees a later index close. On
`weekly.` and `monthly.` it is the period's last index close. Without a stored
index series it is unknown. `index_close > sma(index_close, 200)` is the
market-regime test the Checklist uses.

Names are lowercase. Strings appear only as keyword values. Arguments go by
position or by name: `bb(20, k=2.5)`. Defaults may be left out: `rsi()` is
`rsi(14)`.

## Functions

**Indicators** (the chart's own registry, on the bars of the expression's
timeframe): `rsi(n=14)`, `macd(fast=12, slow=26, signal=9)` with outputs
`.macd` (default), `.signal`, `.histogram`; `stoch(k=14, d=3)` `.k`
(default), `.d`; `adx(n=14)` `.adx` (default), `.plus_di`, `.minus_di`;
`supertrend(n=10, k=3)` `.line` (default), `.direction` (1 up, -1 down);
`bb(n=20, k=2)`, `donchian(n=20)`, `keltner(n=20, k=2, atr_n=10)` with
`.upper`, `.middle`, `.lower` (one must be named); `atr(14)`, `hv(20)`,
`cci(20)`, `roc(12)`, `willr(14)`, `mfi(14)`, `rvol(20)`, `wma(20)`,
`vwap(20)`, `obv()`, `ad()`.

**On any series:** `sma(x, n)`, `ema(x, n)`, `highest(x, n)`,
`lowest(x, n)`, `sum(x, n)`, `change(x, n=1)`, `pct_change(x, n=1)`
(percent), `abs(x)`, `min(a, b, ...)`, `max(a, b, ...)`. Indicators of
indicators work the same way: `ema(rsi(14), 10)`, `ema(obv(), 20)`.

**On a condition:** `count_true(cond, n)` (how many of the last n bars it
held), `bars_since(cond)` (0 when it holds now).

**Relative strength:** `rs(n)`, the percent by which the symbol's n-bar
return beat its market index's (`^GSPC` for US listings, `^NSEI` for
Indian ones).

**Fundamentals** (`fundamental.`): `market_cap`, `enterprise_value`, `pe`,
`pb`, `ps`, `ev_ebitda`, `ev_revenue`, `p_fcf`, `dividend_yield`,
`gross_margin`, `operating_margin`, `net_margin`, `roe`, `roa`,
`roic_pretax`, `debt_to_equity`, `current_ratio`, `payout_ratio`,
`revenue_growth`, `net_income_growth`. Margins, returns and growth are
percentages. Each is the valuation page's figure as known on the bar's date.

## Rules that keep it honest

- **Unknown is not false.** A comparison with missing data is unknown, and
  logic follows Kleene: `false and unknown` is false, `true or unknown` is
  true, `not unknown` is unknown. A screen lists unknown symbols apart, with
  the reason ("no fundamentals known on 2017-03-01", "sma(close, 200): not
  enough history").
- **No look-ahead.** A rule judged on a bar sees only bars up to it,
  fundamentals with `available_at` on or before its date, and news
  available by that session's close. The test suite proves the whole-history
  result equals the result computed from data cut at each bar.
- **Weekly and monthly** use only closed periods: on a daily bar,
  `weekly.close` is the close of the last week that has ended (the venue's
  last session of that week has traded), never the week still running.
- **Point-in-time values** (`fundamental.*`, `news.*`) have no bar history
  in a rule: no `[n]`, moving average, crossing or timeframe prefix.

## Canonical form

Every rule prints back in one canonical text: arguments written out,
defaults filled in, and `and` / `or` parts sorted. Its SHA-256 identifies
the rule, so `rsi() < 30 and close > sma(close, 200)` and `close >
sma(close, n=200) and rsi(14)<30` are the same rule with the same hash.
Comparisons keep their direction: `open < close` and `close > open` are
different texts.

## Trying a rule

```
uv --directory apps/api run python -m stockviz.cli rule-check \
  "close > sma(close, 200) and rsi(14) < 70" AAPL MSFT --explain
```

It prints the canonical text, the hash and the warm-up the rule needs, then
met / not_met / unknown per ticker at the latest completed session (or
`--date`), with the reasons and, with `--explain`, every part's value. A
syntax or type error prints its line and column and exits 2.

## In the screener

`/screener` has a Rule panel above the results. The filters on the left
narrow the list first; the rule then judges each remaining symbol and the
page is sorted and paged after that. Choose **Met only** (the default) or
**Show all with result** to see every symbol with met, not met or unknown and
why. The rule is in the address (`?rule=...`), so a screen with a rule can be
shared as a link or saved as a screen.

Each market is judged on one session: the newest stored close on or before
its latest completed session. A symbol whose own data stops before that day
is unknown ("no bar for 2026-11-24; latest 2026-11-20"), not judged on old
prices. The API takes `as_of=YYYY-MM-DD` to judge an earlier session; the
symbol list is today's, so a past date shows only today's survivors.

API: `GET /v1/screener?rule=<text>&rule_mode=met_only|all[&as_of=]`, or
`setup_version_id=<id>` for a saved version. `POST /v1/rules/check` with
`{"rule": "..."}` returns the canonical text, hash and warm-up, or the error
with its line and column.

## Setups

A **setup** is a saved rule. Signed in, "Save as setup" stores the rule as
version 1; a changed rule is a new version, and an old version never changes,
so anything that names a version keeps its exact rule. Saving a rule a setup
already has (same canonical text) returns that version. `/setups` lists your
setups and the presets.

## Presets

Read-only setups shipped with StockViz, using only data it holds. Fork one to
change it. Each one's page says where its formula comes from and what it
leaves out.

| Preset | Rule |
| --- | --- |
| Minervini trend template | `close > sma(close, 150) and close > sma(close, 200) and sma(close, 150) > sma(close, 200) and sma(close, 200) > sma(close, 200)[21] and sma(close, 50) > sma(close, 150) and sma(close, 50) > sma(close, 200) and close > sma(close, 50) and close >= 1.3 * lowest(low, 252) and close >= 0.75 * highest(high, 252) and rs(252) > 0` |
| 52-week-high breakout on rising volume | `close > highest(high, 252)[1] and volume >= 1.5 * sma(volume, 50) and sma(volume, 10) > sma(volume, 50)` |
| RSI pullback in an uptrend | `close > sma(close, 200) and sma(close, 50) > sma(close, 200) and rsi(2) < 10` |
| Piotroski-style quality screen | `fundamental.roa > 0 and fundamental.p_fcf > 0 and fundamental.debt_to_equity < 1 and fundamental.current_ratio > 1` |

- **Minervini** (Trade Like a Stock Market Wizard, 2013): all eight points;
  the eighth, an IBD relative-strength rating of 70 or more, is approximated
  by `rs(252) > 0` (the 12-month return beat the market index).
- **Breakout** (Darvas; O'Neil): a close above the previous 252 sessions'
  high on volume at least 1.5 times its 50-day average, with the 10-day
  average volume above the 50-day. The 1.5x is a convention.
- **RSI pullback** (Connors and Alvarez, Short Term Trading Strategies That
  Work, 2008): RSI(2) under 10 above the 200-day average, plus the 50-day
  above the 200-day. Entry condition only.
- **Piotroski-style** (Piotroski, 2000): F1 (ROA above zero) exactly; F2
  (operating cash flow above zero) by positive free cash flow, stricter, and
  unknown when free cash flow is negative; F5 and F6 replaced by levels (debt
  to equity under 1, current ratio above 1). F3, F4, F7, F8 and F9 need
  year-over-year history the DSL does not read yet.

Every preset is in the conformance suite, so its scan and its bar-by-bar
results are proven equal. None is a recommendation.


## The Checklist

The Checklist (`/checklist`, A2.4) replaced the 7-vote Signals. It judges six
dimensions, each a short list of conditions written in this language and
stored as a read-only system setup of kind `checklist` (versioned and hashed
like any preset; `/v1/setups/presets` lists them). A dimension is **met**
when all its conditions are met, **unknown** when an input is missing and no
condition failed, and **not met** otherwise: Kleene's `and`, exactly what the
DSL gives the conjunction. The page reads "N of 6 met". It never says buy or
sell.

| Dimension | Conditions | Source |
| --- | --- | --- |
| Trend | `close > sma(close, 200)`; `sma(close, 50) > sma(close, 200)` | trend-following's 200-day filter; points of Minervini's template |
| Momentum / relative strength | `rs(126) > 0`; `rsi(14) >= 50`; `rsi(14) <= 70` | Jegadeesh and Titman (1993) 6-month momentum; Wilder's RSI, the 50-70 bull range (Cardwell, Brown) |
| Volume / delivery | `volume > sma(volume, 50)`; on NSE and BSE listings also `delivery_pct > 50` | O'Neil's volume test; NSE/BSE delivery data. US listings have no delivery figure, so they are judged on volume (a separate setup). Indian delivery is unknown until NSE files load (A1) |
| Market regime | `index_close > sma(index_close, 200)` | Faber (2007): the index above its 10-month (here 200-day) average |
| Quality | `fundamental.roe > 15`; `fundamental.debt_to_equity < 1` | common ROE cut-off; Graham's defensive balance-sheet test. Unknown before fundamentals were collected |
| Risk / reward | `close >= 0.75 * highest(high, 252)`; `atr(14) < 0.04 * close` | Minervini's "within 25% of the high"; Wilder's ATR, a 4% bound (a convention) |

**Nightly.** `stockviz.cli checklist` (cron, after `metrics`) judges every
active symbol's six dimensions at its venue's latest stored session (a symbol
without that day's bar is unknown, never judged stale) into
`checklist_scores`. `GET /v1/checklist` and `GET /v1/symbols/{t}/checklist`
return the results with each dimension's formula, grade and sample.

**Evidence grade.** `stockviz.cli checklist-evidence` (Fridays) studies each
dimension setup on the stored history (default: the last 10 years):

- an **event** is the first bar the rule is true after a bar it was false
  (vector mode, conformance-proven, so no value depends on a later bar);
- its **outcome** is the forward 20-session close-to-close return, minus the
  venue's round-trip fees (`us_equity_2026`, `in_delivery_nse_2026` or
  `in_delivery_bse_2026` on a 100,000 position; dividends not added);
- its **excess** is that minus the **base rate**: the mean forward 20-session
  return, before costs, of every symbol in the same universe and market on the
  same date;
- events on one symbol within 20 bars of the last counted one are skipped, so
  windows on a symbol never overlap (windows on different symbols still can);
- the grade: **A** when t >= 3 and the mean excess >= 1%, **B** when t >= 2,
  **C** when t >= 1, **D** otherwise, **insufficient** under 30 events.

Every grade carries its sample (events, symbols, window, horizon) and the
universe stamp: the pinned symbol list with today's provider history, so the
study sees only survivors and is **survivorship-biased** until A1.4b's
point-in-time universes. Grades describe past association net of modelled
costs, not a forecast, and are not advice.
