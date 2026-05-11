# stockviz-api

FastAPI backend for StockViz. Serves market data, news, and paper-trading portfolios.

## Dev

```powershell
# from repo root
docker compose -f infra/docker-compose.yml up -d
uv --directory apps/api run alembic upgrade head
uv --directory apps/api run uvicorn stockviz.main:app --reload --port 8000
```

OpenAPI docs at http://localhost:8000/docs.

## Layout

```
src/stockviz/
├── main.py          # FastAPI app factory
├── settings.py      # pydantic-settings, reads from env
├── db.py            # engine + session dependency
├── routers/         # HTTP endpoints, one module per resource
├── models/          # SQLModel models (DB tables)
├── services/        # business logic, called by routers
│   ├── ingest/      # data fetching from Alpha Vantage / yfinance / Newsdata
│   ├── indicators/  # technical indicators (SMA, EMA, RSI, MACD)
│   └── recommend/   # recommendation algorithm
└── scheduler.py     # APScheduler job definitions
```

## Tests

```powershell
uv --directory apps/api run pytest
```
