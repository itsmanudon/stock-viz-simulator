# stockviz-api

FastAPI backend for StockViz. Serves end-of-day market data, news, strategy
backtests, FX-aware equity paper trading, and a long-only options book
(Black-Scholes; premiums debit USD cash and are not a full multi-currency
options ledger).

Quote SSE at `/v1/stream/quotes/{ticker}` is a **simulated** random walk from
the last cached close, not an exchange real-time feed.

## Dev

```powershell
# from repo root
docker compose -f infra/docker-compose.yml up -d
uv --directory apps/api run alembic upgrade head
uv --directory apps/api run uvicorn stockviz.main:app --reload --port 8000
```

OpenAPI docs at http://localhost:8000/docs.

Full local setup (seed, backfill, web app): [`docs/SETUP.md`](../../docs/SETUP.md).

## Layout

```
src/stockviz/
├── main.py          # FastAPI app factory
├── settings.py      # pydantic-settings, reads from env
├── db.py            # engine + session dependency
├── routers/         # HTTP endpoints, one module per resource
├── models/          # SQLModel models (DB tables)
├── services/        # business logic, called by routers
│   ├── ingest/      # yfinance (primary) / Alpha Vantage (fallback) / Newsdata
│   ├── indicators/  # SMA, EMA, RSI, MACD
│   ├── recommend/   # daily scoring
│   ├── trading/     # fills, orders, FX, dividends, analytics
│   ├── options/     # Black-Scholes + long options book
│   ├── backtest/    # historical strategy replay
│   └── sentiment/   # optional headline scoring
└── scheduler.py     # APScheduler job definitions
```

## Tests

```powershell
uv --directory apps/api run pytest
```
