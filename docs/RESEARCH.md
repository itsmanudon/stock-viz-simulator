# Research domain

StockViz Research is a quantitative workspace inside the product shell. It is not a combined dashboard and not an AI advisory product.

```
Markets / Screener  →  /stocks/[ticker]  →  Research
                                            ├── /compare
                                            ├── /backtest
                                            ├── /recommendations  (Signals)
                                            └── /replay           (Replay Lab, signed-in)
```

## Routes and URL state

| Route | Purpose | Shareable state |
| --- | --- | --- |
| `/compare` | Normalized relative performance | `tickers` (canonical; `symbols` alias), `tf` (`1M`…`5Y`) |
| `/backtest` | Historical rule replay | `ticker` prefills the experiment |
| `/recommendations` | Explainable technical + sentiment votes | `min`, `signal` (`bullish`\|`neutral`\|`all`), `sector`, `q`, `sort`, `dir` |
| `/replay` | Blind historical Replay Lab | session id is `/replay/[id]`; optional `ticker` on the launcher |

Deep links and back/forward must keep working. Do not hide these filters in client-only stores.

Replay Lab is **future-blind**. The workspace chart and quote come only from `/v1/replay/sessions/{id}/history` and `/market`. Forensics and journal use `/forensics` and `/journal` on the same session. Do not fetch generic bars, live quotes, SSE, news, comments, or fundamentals into a replay session. `/replay/[id]?view=forensics` is a sub-view of the session, not a new Research domain.

## Server / client boundaries

- **Compare** is a Server Component. It loads bars in parallel and optionally joins screener metrics. Client islands: symbol picker, normalized chart.
- **Backtest** is a Server Component that loads the symbol universe. The experiment form, run, and result rendering are one public-client island (`POST /v1/backtest` is unauthenticated).
- **Signals** is a Server Component. Filters are links. Row expansion uses native `<details>` so evidence does not require a client bundle.

Optional fetches (`screenSymbols`, sentiment columns) use `catch` so a metrics outage still renders price-derived research.

## Backend limitations (intentional)

- Prices are end-of-day `1d` bars. The quote badge on stock pages is a simulated random walk from the latest close, not a live tape.
- Compare volatility and max drawdown are **window statistics of the loaded closes**, not a risk engine. Sharpe, beta, alpha, and correlation are not shown there because the compare APIs do not provide them.
- Backtests are all-in / all-out, next-bar fills, and optional bps costs. They are not brokerage-grade microstructure simulation. Sharpe uses the engine’s 5% annual risk-free rate.
- Signals are a deterministic 7-vote scorer (six price/volume checks plus optional trailing news sentiment). `score >= 4` is bullish; lower scores are neutral. There is no bearish model. Sentiment is skipped (not penalised) when no headlines are scored.
- Recommendation rows are precomputed by the daily job / `stockviz recommend`. The list endpoint serves the latest row per ticker and now includes structured `votes` (and reconstructs them from stored rationale for older rows).

## Extension seams

- Additional compare factors belong behind real APIs, not client invention.
- Additional backtest strategies belong in `apps/api/src/stockviz/services/backtest/` with the same next-bar contract.
- Bearish or multi-horizon signals would be a new model, not a relabel of the current score.
- A later market-replay / execution simulator should replace this backtest UI’s assumptions rather than quietly widening them.
