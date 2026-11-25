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
| Bar series | `open high low close volume`; `delivery_pct deliverable_qty` (NSE, daily only) |
| Arithmetic | `+ - * /` and unary `-`; division by zero is unknown |
| Comparison | `< <= > >= = !=` (`==` also means `=`). One per condition: write `a < b and b < c` |
| Logic | `and`, `or`, `not`, parentheses |
| Crossing | `a crosses_above b`: above now, at or below on the bar before (`crosses_below` mirrors it) |
| Offset | `x[n]`: `x` n bars ago, on `x`'s own timeframe (`weekly.close[1]` is last week's close) |
| Timeframe | `weekly.x`, `monthly.x`, `weekly.(close > open)` |
| Fundamentals | `fundamental.<metric>` |
| News | `news.count(days, sentiment="...", event_type="...")` |
| Comments | `# to the end of the line` |

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
