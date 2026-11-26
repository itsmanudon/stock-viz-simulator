# Research domain

StockViz Research is a quantitative workspace inside the product shell. It is not a combined dashboard and not an AI advisory product.

```
Markets / Screener  →  /stocks/[ticker]  →  Research
                                            ├── /compare
                                            ├── /backtest
                                            ├── /checklist        (Checklist; /recommendations redirects)
                                            ├── /event-study      (A4.5: what followed a DSL trigger)
                                            ├── /news-reactions   (Phase 7.4: CAR around news)
                                            └── /replay           (Replay Lab, signed-in)
```

## Routes and URL state

| Route | Purpose | Shareable state |
| --- | --- | --- |
| `/compare` | Normalized relative performance | `tickers` (canonical; `symbols` alias), `tf` (`1M`…`5Y`) |
| `/backtest` | Historical rule replay: two templates, (A4.1) a Rule DSL strategy, or (A4.4) a cross-sectional rotation | `ticker` prefills the experiment; `mode=rule` opens the Rule strategy mode, `mode=rotation` the Rotation mode |
| `/event-study` | A4.5: forward 5/20/60-session returns net of costs after a Rule DSL trigger turned true, against the base rate | `rule` or `setup`, `market` \| `tickers` \| `watchlist`, `from`, `to`, `cooldown` |
| `/news-reactions` | Phase 7.4: market-adjusted returns around Aegis news of a kind | `tickers`, `sentiment`, `event_type`, `pre`, `post` |
| `/checklist` | Six Rule DSL dimensions, "N of 6 met", formulas and evidence grades | `min`, `dimension`, `sort` (`met`\|`ticker`), `q` |
| `/replay` | Blind historical Replay Lab | session id is `/replay/[id]`; optional `ticker` on the launcher |

Deep links and back/forward must keep working. Do not hide these filters in client-only stores.

Replay Lab is **future-blind**. The workspace chart and quote come only from `/v1/replay/sessions/{id}/history` and `/market`. Forensics and journal use `/forensics` and `/journal` on the same session. Do not fetch generic bars, live quotes, SSE, news, comments, or fundamentals into a replay session. `/replay/[id]?view=forensics` is a sub-view of the session, not a new Research domain.

## Server / client boundaries

- **Compare** is a Server Component. It loads bars in parallel and optionally joins screener metrics. Client islands: symbol picker, normalized chart.
- **Backtest** is a Server Component that loads the symbol universe. The template form and result rendering are one client island; since A4.3 its runs go through a server action (`runTemplateAction`) to `POST /v1/backtest`, authed when signed in, so each run lands in the caller's trial ledger (signed out: the anonymous pool, 20 runs a minute per visitor). The Rule strategy mode (`?mode=rule`, A4.1) also loads the presets and, signed in, your setups and watchlists; its runs go through a server action (`runStrategyAction`) to `POST /v1/backtest/strategy`, authed when signed in, so a watchlist universe and your own setup versions work.
- **Rotation** (`?mode=rotation`, A4.4) is a client island like the Rule strategy mode; runs go through `runRotationAction` to `POST /v1/backtest/rotation` (authed when signed in).
- **Event study** (A4.5) is a Server Component: the form is a GET form (the study is the URL), the page runs `POST /v1/research/scan-event-study` on the server, as you when signed in (watchlists, your setups), else public with 10 studies a minute per visitor. The screener's rule panel and `/setups` link to it ("Run event study").
- **Checklist** is a Server Component. Filters are links. Symbol and dimension expansion uses native `<details>`, so formulas, reasons and grades need no client bundle.

Optional fetches (`screenSymbols`, sentiment columns) use `catch` so a metrics outage still renders price-derived research.

## Backend limitations (intentional)

- Prices are end-of-day `1d` bars. The quote badge on stock pages is a simulated random walk from the latest close, not a live tape.
- Compare volatility and max drawdown are **window statistics of the loaded closes**, not a risk engine. Sharpe, beta, alpha, and correlation are not shown there because the compare APIs do not provide them.
- Template backtests are all-in / all-out, next-bar fills, and optional bps costs. They are not brokerage-grade microstructure simulation. Sharpe uses the engine’s 5% annual risk-free rate.
- Rule strategies (A4.1, M7.1): an entry rule and an optional exit rule in the Rule DSL (a setup version or typed text), signals from vector mode, orders on the next bar through the execution kernel. Stops: fixed %, ATR multiple, trailing (% or ATR), time (N bars); judged on each bar's high and low, a gap through a stop fills at the open and is flagged, and the stop nearest the open is hit first. Sizing: all in, a fraction of equity, or a fixed % of equity at risk to the initial stop; whole shares. R = net P&L / initial risk. Universe: one symbol, a watchlist of yours, or up to 50 tickers in one currency, with a max positions cap. Long only; shorts only for US symbols a run declares shortable (Indian shorts wait for the F&O-eligible list). An unknown signal does nothing and is counted. Price return only (no dividends). Results show net first, gross second. The two templates were not rewritten as DSL strategies: they size in fractional shares, support total return and keep their own warm-up, so their numbers would change.
- Report card and overfitting checks (A4.3, M7.4), on both modes and on saved runs. Everything is net of costs. Metrics: CAGR, Sortino, Calmar, win rate, payoff ratio, profit factor, expectancy (money, and R when a stop defines it), exposure, average holding days, closed trades, each with its formula. The **trial ledger** records every run, saved or not, by strategy hash, data fingerprint and user (anonymous runs share one pool; nothing about a visitor is stored); a **strategy family** is the template and ticker, or the rules with numbers replaced by `#` plus the stop kinds, sizing kind, direction and tickers. PSR (against Sharpe 0) and the Deflated Sharpe Ratio (N = the family's distinct variants, variance of their Sharpes) are closed form; with one variant DSR = PSR(0). Sweeps add PBO by CSCV (16 blocks, all 12,870 half-splits) and a parameter-plateau heatmap that flags an isolated best. **Locked holdout**: by default the last 20% of the range is held out of the run, sweeps and walk-forwards; a signed-in user unlocks a family's holdout once (two-step confirm, time recorded), after which every run of the family shows it as seen with its result; `holdout: none` is an explicit, stamped choice. A seeded block-bootstrap fan shows drawdown percentiles, and a regime split shows the run by A3.5's regime as known each day. Worked numbers: [`benchmarks/2026-11-26-a4-report-card.md`](./benchmarks/2026-11-26-a4-report-card.md). Hansen's SPA and White's reality check are for the lab (A9), not the API.
- Rotation (A4.4, M7.1): hold the top N of a universe (a watchlist or up to 50 tickers, one currency) by a numeric Rule DSL ranking (e.g. `pct_change(close, 126)`), higher first; unknown values are never ranked. It ranks on the last session of each week or month on the venue calendar, from values known at that close, and trades on each symbol's next bar; a first ranking on the session before the window makes it invested from the start. Each rebalance resizes to the targets (equal 1/N, or inverse volatility over 63 sessions): leavers sold in full, holders trimmed or topped up, entrants bought; an optional buffer keeps a holding while its rank is at most N + buffer. An optional cash filter, a condition judged on the market index (`index_close < sma(index_close, 200)`), sells everything when met; unknown does nothing. Same kernel fills, dated costs, ADV cap, report card, trial ledger and holdout as rule strategies; results list every rebalance (ranking values, held, in, out, turnover). Method: [`SIMULATION.md`](./SIMULATION.md#cross-sectional-rotation-a44).
- Scan event study (A4.5, M7.3): an event is the session a condition turns true after a session it was false (optional cooldown); outcomes are forward 5/20/60-session returns net of a round trip at the venue's dated fee schedule, with excess over the base rate (every symbol-day of the same universe and market), hit rates, percentiles, a histogram, the t of the mean excess and a t clustered by date; under 30 events only counts. It is A2.4's evidence engine (`checklist/evidence.py::study_horizons`), so the checklist grades are computed by the same code (a test holds them unchanged). Association, not cause; the universe is survivorship-biased.
- The Checklist (A2.4) replaced the 7-vote Signals. Six dimensions (Trend, Momentum/RS, Volume/Delivery, Market regime, Quality, Risk/Reward) are Rule DSL conditions; each is met, not met or unknown (Kleene). It counts conditions; it never says buy or sell. Formulas and sources: [`rule-dsl.md`](./rule-dsl.md#the-checklist).
- Scores are precomputed nightly by `stockviz.cli checklist`; grades weekly by `stockviz.cli checklist-evidence` (forward 20-session return net of fees vs the same-date base rate; A-D, insufficient under 30 events), measured on the survivorship-biased pinned universe until A1.4b.

## Extension seams

- Additional compare factors belong behind real APIs, not client invention.
- Additional backtest strategies are Rule DSL rules now (a setup); engine changes belong in `apps/api/src/stockviz/services/backtest/strategy.py` with the same next-bar contract and fills through `fills.book`.
- A new dimension or changed threshold is a new setup version, graded again; it must join the DSL conformance corpus first.
- A later market-replay / execution simulator should replace this backtest UI’s assumptions rather than quietly widening them.
