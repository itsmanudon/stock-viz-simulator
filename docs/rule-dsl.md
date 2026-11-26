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
close crosses_above drawing("support").price
close > avwap("swing") and close < avwap("swing").upper2
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
| Your drawings (A3.3) | `drawing("label").price`, `.top`, `.bottom`; `avwap("label")` and `.upper1 .lower1 .upper2 .lower2` |
| Comments | `# to the end of the line` |

`index_close` is the close of the listing's market index on each bar's date:
`^GSPC` for US listings, `^NSEI` for Indian ones, forward-filled at most 5
bars (the series `rs()` reads). A bar never sees a later index close. On
`weekly.` and `monthly.` it is the period's last index close. Without a stored
index series it is unknown. `index_close > sma(index_close, 200)` is the
market-regime test the Checklist uses.

Names are lowercase. Strings appear only as keyword values and as a
drawing's label in `drawing("...")` and `avwap("...")`. Arguments go by
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

**Added in A3.4** (each with its parameters' bounds from the registry; out
of bounds is a type error, as on the chart and the API):

- Moving averages: `hma(n=20)`, `dema(n=20)`, `tema(n=20)`,
  `kama(n=10, fast=2, slow=30)`.
- `psar(step=0.02, max=0.2)` `.sar` (default; the stop in force on the bar,
  from the bars before it), `.direction` (1 up, -1 down, after the bar's
  reversal check).
- `ichimoku(tenkan=9, kijun=26, senkou=52, shift=26)` with `.tenkan`,
  `.kijun`, `.senkou_a`, `.senkou_b` (one must be named). A leading span on
  a bar is the span *drawn on that bar*, computed `shift` bars earlier, so a
  rule never reads a later bar; there is no lagging span (it would put a
  later close on an earlier bar).
- `pivots(basis=3)` `.pp` (default), `.r1`, `.r2`, `.s1`, `.s2`: classic
  floor pivots from the prior bar (1), week (2), month (3) or year (4).
- Trend and momentum: `aroon(n=25)` `.up` / `.down`; `vortex(n=14)` `.plus`
  / `.minus`; `elder(n=13)` `.bull` / `.bear`; `chop(14)`, `trix(15)`,
  `cmo(9)`, `uo(short=7, mid=14, long=28)`, `coppock(long=14, short=11,
  n=10)`; `tsi(long=25, short=13, signal=7)` `.tsi` (default), `.signal`;
  `ppo(12, 26, 9)` `.ppo` (default), `.signal`, `.histogram`;
  `stochrsi(rsi_n=14, n=14, k=3, d=3)` `.k` (default), `.d` (0-100).
- Volatility: `natr(14)` (ATR % of close), `massi(n=9, total=25)`,
  `rmv(n=5, lookback=50)` (StockViz's range tightness: 0 = the tightest
  n-bar range of `lookback` bars, 100 the widest).
- Volume: `cmf(20)`, `chaikin(fast=3, slow=10)`, `force(13)`, `eom(14)`.
- `rsline()`: the close over the venue index's close (`^GSPC`, `^NSEI`),
  the index forward-filled at most 5 bars; unknown without an index.

Each study's **canonical signal**, graded on the chart's evidence badge,
is a rule in this language; the list is
`apps/api/src/stockviz/services/indicators/signals.py` (for example `rsi(14)
crosses_above 30`, `psar(0.02, 0.2).direction crosses_above 0`, `close
crosses_above max(ichimoku(9, 26, 52, 26).senkou_a, ichimoku(9, 26, 52,
26).senkou_b)`).

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

## Your drawings and anchored VWAPs (A3.3)

A rule can read the chart drawings you saved on a symbol, by their label
(labels match ignoring case and extra spaces). On a daily bar dated `d`:

| Binding | Drawing | Value |
| --- | --- | --- |
| `drawing("x").price` | horizontal line | its price, on every bar |
| `drawing("x").price` | trend line | linear between its two anchors, by weekdays (Monday to Friday); only from the earlier anchor's date to the later one's, inclusive. Before or after: unknown. It is not extended; draw a ray for that |
| `drawing("x").price` | ray | linear through its two anchors and extended past the second. It runs from its first point towards the second: drawn to the right, it has a value on every bar from the first point on; drawn to the left, on every bar up to it |
| `drawing("x").top`, `.bottom` | rectangle | its higher and lower price, on every bar from its left edge on (a zone keeps its level after it is drawn); unknown before |
| `avwap("x")` | anchored VWAP | the VWAP from its anchor date over the daily bars up to each bar; unknown before the anchor. `.upper1 .lower1 .upper2 .lower2` are the bands at one and two volume-weighted standard deviations |

- **Weekdays, not sessions.** The daily chart draws a line straight through
  its bars, so it is linear in sessions; a rule reads it linear in weekdays,
  which differ only by the exchange holidays between the anchors (a few
  sessions of slope at most). Weekdays are known in advance, so a line's
  value on a bar never depends on bars that come later.
- **No look-ahead.** A drawing's value on a bar reads only its anchors, and an
  AVWAP only bars up to that bar. A line that starts after a bar is unknown
  on it. A drawing you drew later is still applied to earlier bars: it is
  your geometry, not data. The conformance suite checks both modes and the
  perturb-the-future test with drawings in its test data.
- **Daily only.** `weekly.drawing(...)` is an error. On a weekly or monthly
  chart, the AVWAP is the daily one sampled at each bar's last session.
- **Unknown, never a crash.** A label with no drawing ("drawing 'x' not
  found"), two drawings with one label, a kind the binding cannot read (a
  Fibonacci, a text note; `.price` on a rectangle), or a deleted or renamed
  drawing all make the value unknown with the reason. An alert on such a
  rule stays quiet (unknown never fires).
- **Yours only.** These rules are *user-scoped*: they resolve only for their
  owner. `POST /v1/rules/check` says `user_scoped: true` (and `uses`
  includes `drawings`); the rule editor notes "Uses your drawings; only you
  can run it". The screener runs such a rule for the signed-in user only
  (signed out it is refused, 401), and never caches it; a rule alert reads
  the alert owner's drawings; a nightly saved-screen run reads the setup
  owner's. A preset cannot hold one, and another user cannot fork a setup
  that uses one. `rule-check` reads `--user-id N`'s drawings; without it the
  values are unknown.

An anchored VWAP is a drawing of kind `avwap` (one date, a label, its bands).
On the stock page pick the "Anchored VWAP" tool and click the anchor bar,
or anchor at the highest high or lowest low of the loaded bars or the last
earnings date, or add one by typing a date in the Drawings list. The chart
reads `GET /v1/symbols/{t}/avwap?anchor=YYYY-MM-DD&interval=1d|1wk|1mo&bands=0|1|2`.

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
syntax or type error prints its line and column and exits 2. A rule that
reads drawings needs `--user-id N` (whose drawings it reads).

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
with its line and column. With `"expect": "number"` (A4.4) it checks a
numeric expression instead, such as a rotation's ranking
(`pct_change(close, 126)`); a condition is then an error.

## Rotations and event studies (A4)

- **Rotation ranking** (`/backtest?mode=rotation`): any numeric expression,
  higher ranks first, read at each rebalance session's close; unknown values
  are not ranked. The optional cash filter is a condition on the market
  index, written with `index_close` (e.g. `index_close < sma(index_close,
  200)`).
- **Event study** (`/event-study`): any condition is a trigger; an event is
  the session it turns true after a session it was false. News and delivery
  triggers are rules: `news.count(1) >= 1`, `news.count(1,
  sentiment="negative") >= 1`, `delivery_pct > 60`, `delivery_pct > 1.5 *
  sma(delivery_pct, 20)`. "Run event study" on the screener's rule panel and
  on a setup opens it with the rule.

## Intraday timeframes (A6.4)

A rule is judged on **daily bars** unless its setup version (or a backtest)
names an intraday **timeframe**: `1m`, `5m`, `15m`, `30m` or `60m`. The rule
text is the same language; on an intraday timeframe `close`, `rsi(14)` and
every other series and indicator read that timeframe's bars, built from the
stored minutes (bars never cross a night, a weekend or a pause), and the
warm-up is counted in those bars. Intraday bars are judged only once they
are **closed**.

- **Instants.** Each intraday bar is its open instant (UTC) and its close.
  A rule's value on a bar uses only what was known at that bar's close.
- **`daily.`** reads daily bars on an intraday timeframe: `close >
  daily.high[1]`, `daily.close crosses_above daily.sma(close, 10)`. A
  `daily.` value on a bar is the value on the **most recent completed
  session strictly before the bar's session**: yesterday's, all day, even
  at today's last bar (today's daily bar is not complete until after the
  close). On a Muhurat evening or a DR-pause day the same rule holds.
  `weekly.` and `monthly.` work too, as of that same previous session.
  `daily.` does not exist on the daily timeframe (write the expression
  without it), and prefixes do not nest.
- **Per binding** on an intraday timeframe:

  | Binding | Intraday |
  | --- | --- |
  | `open high low close volume`, every indicator and primitive | on the intraday bars |
  | `fundamental.*` | read at each bar: facts dated **before** the bar's session (a filing dated today is not known at a given minute of today), the bar's close as the price. No prefix |
  | `news.count(...)` | read at each bar: documents with `available_at` at or before the **bar's close**. No prefix |
  | `index_close`, `rs(n)`, `rsline()` | daily only: write `daily.index_close`, `daily.rs(20)` (the index's closes are daily) |
  | `delivery_pct`, `deliverable_qty` | daily only: write `daily.delivery_pct` |
  | `drawing("x")`, `avwap("x")` | daily only (drawings anchor on daily bars): write `daily.drawing("x").price` |

- **Checking.** `POST /v1/rules/check` takes `timeframe`; the backtest
  form's picker offers the intraday timeframes only for a symbol whose
  minutes are stored, and checks the rule for the timeframe picked.
- **Proof.** `tests/test_dsl_intraday_conformance.py`: every intraday rule
  in its corpus gives the same value bar by bar (as a stream judges) as
  over the whole history, on synthetic NSE minutes with the 2 Mar 2024 DR
  pause and the 1 Nov 2024 Muhurat evening and on XNYS minutes with a half
  day; changing later bars, today's daily bar, later facts or later news
  changes no value up to the bar.

## Setups

A **setup** is a saved rule. Signed in, "Save as setup" stores the rule as
version 1; a changed rule is a new version, and an old version never changes,
so anything that names a version keeps its exact rule. Saving a rule a setup
already has (same canonical text) returns that version. `/setups` lists your
setups and the presets. Since A6.4 a version also carries its **timeframe**
(daily, or `1m` ... `60m`) and **feed** (`auto`: the best stored); the same
rule on another timeframe is another version. The screener, screens, event
studies, drills and rotations read daily versions only. The backtest's
Rule strategy form saves its entry rule as an alert setup on the timeframe
picked ("Save as 5 minutes setup"), and a rule alert on it is judged on each
closed bar (`apps/api/CLAUDE.md`, "Intraday rules (A6.4)").

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
