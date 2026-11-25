# Research domain

StockViz Research is a quantitative workspace inside the product shell. It is not a combined dashboard and not an AI advisory product.

```
Markets / Screener  →  /stocks/[ticker]  →  Research
                                            ├── /compare
                                            ├── /backtest
                                            ├── /checklist        (Checklist; /recommendations redirects)
                                            └── /replay           (Replay Lab, signed-in)
```

## Routes and URL state

| Route | Purpose | Shareable state |
| --- | --- | --- |
| `/compare` | Normalized relative performance | `tickers` (canonical; `symbols` alias), `tf` (`1M`…`5Y`) |
| `/backtest` | Historical rule replay: two templates, or (A4.1) a Rule DSL strategy | `ticker` prefills the experiment; `mode=rule` opens the Rule strategy mode |
| `/checklist` | Six Rule DSL dimensions, "N of 6 met", formulas and evidence grades | `min`, `dimension`, `sort` (`met`\|`ticker`), `q` |
| `/replay` | Blind historical Replay Lab | session id is `/replay/[id]`; optional `ticker` on the launcher |

Deep links and back/forward must keep working. Do not hide these filters in client-only stores.

Replay Lab is **future-blind**. The workspace chart and quote come only from `/v1/replay/sessions/{id}/history` and `/market`. Forensics and journal use `/forensics` and `/journal` on the same session. Do not fetch generic bars, live quotes, SSE, news, comments, or fundamentals into a replay session. `/replay/[id]?view=forensics` is a sub-view of the session, not a new Research domain.

## Server / client boundaries

- **Compare** is a Server Component. It loads bars in parallel and optionally joins screener metrics. Client islands: symbol picker, normalized chart.
- **Backtest** is a Server Component that loads the symbol universe. The template form, run, and result rendering are one public-client island (`POST /v1/backtest` is unauthenticated). The Rule strategy mode (`?mode=rule`, A4.1) also loads the presets and, signed in, your setups and watchlists; its runs go through a server action (`runStrategyAction`) to `POST /v1/backtest/strategy`, authed when signed in, so a watchlist universe and your own setup versions work.
- **Checklist** is a Server Component. Filters are links. Symbol and dimension expansion uses native `<details>`, so formulas, reasons and grades need no client bundle.

Optional fetches (`screenSymbols`, sentiment columns) use `catch` so a metrics outage still renders price-derived research.

## Backend limitations (intentional)

- Prices are end-of-day `1d` bars. The quote badge on stock pages is a simulated random walk from the latest close, not a live tape.
- Compare volatility and max drawdown are **window statistics of the loaded closes**, not a risk engine. Sharpe, beta, alpha, and correlation are not shown there because the compare APIs do not provide them.
- Template backtests are all-in / all-out, next-bar fills, and optional bps costs. They are not brokerage-grade microstructure simulation. Sharpe uses the engine’s 5% annual risk-free rate.
- Rule strategies (A4.1, M7.1): an entry rule and an optional exit rule in the Rule DSL (a setup version or typed text), signals from vector mode, orders on the next bar through the execution kernel. Stops: fixed %, ATR multiple, trailing (% or ATR), time (N bars); judged on each bar's high and low, a gap through a stop fills at the open and is flagged, and the stop nearest the open is hit first. Sizing: all in, a fraction of equity, or a fixed % of equity at risk to the initial stop; whole shares. R = net P&L / initial risk. Universe: one symbol, a watchlist of yours, or up to 50 tickers in one currency, with a max positions cap. Long only; shorts only for US symbols a run declares shortable (Indian shorts wait for the F&O-eligible list). An unknown signal does nothing and is counted. Price return only (no dividends). Results show net first, gross second. The two templates were not rewritten as DSL strategies: they size in fractional shares, support total return and keep their own warm-up, so their numbers would change.
- The Checklist (A2.4) replaced the 7-vote Signals. Six dimensions (Trend, Momentum/RS, Volume/Delivery, Market regime, Quality, Risk/Reward) are Rule DSL conditions; each is met, not met or unknown (Kleene). It counts conditions; it never says buy or sell. Formulas and sources: [`rule-dsl.md`](./rule-dsl.md#the-checklist).
- Scores are precomputed nightly by `stockviz.cli checklist`; grades weekly by `stockviz.cli checklist-evidence` (forward 20-session return net of fees vs the same-date base rate; A-D, insufficient under 30 events), measured on the survivorship-biased pinned universe until A1.4b.

## Extension seams

- Additional compare factors belong behind real APIs, not client invention.
- Additional backtest strategies are Rule DSL rules now (a setup); engine changes belong in `apps/api/src/stockviz/services/backtest/strategy.py` with the same next-bar contract and fills through `fills.book`.
- A new dimension or changed threshold is a new setup version, graded again; it must join the DSL conformance corpus first.
- A later market-replay / execution simulator should replace this backtest UI’s assumptions rather than quietly widening them.
