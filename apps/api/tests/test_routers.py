"""HTTP-level tests for the /v1 routers.

Uses the SQLite session fixture from conftest. Each test seeds the DB with
the minimum data it needs and exercises one endpoint.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlmodel import Session

from stockviz.models import NewsArticle, PriceBar, Symbol


def _seed_symbol(session: Session, ticker: str = "AAPL", **kw) -> Symbol:
    sym = Symbol(
        ticker=ticker,
        name=kw.get("name", "Apple Inc."),
        **{k: v for k, v in kw.items() if k != "name"},
    )
    session.add(sym)
    session.commit()
    session.refresh(sym)
    return sym


def _seed_bar(
    session: Session,
    ticker: str,
    ts: datetime,
    *,
    close: str = "100.00",
    interval: str = "1d",
) -> PriceBar:
    bar = PriceBar(
        ticker=ticker,
        ts=ts,
        interval=interval,
        open=Decimal(close),
        high=Decimal(close),
        low=Decimal(close),
        close=Decimal(close),
        volume=1_000_000,
        source="test",
    )
    session.add(bar)
    session.commit()
    return bar


# ---------------------------------------------------------------------------
# /v1/symbols
# ---------------------------------------------------------------------------


def test_list_symbols_returns_active_sorted(session: Session, client: TestClient) -> None:
    _seed_symbol(session, "AAPL", name="Apple")
    _seed_symbol(session, "MSFT", name="Microsoft")
    _seed_symbol(session, "OLD", name="Delisted", is_active=False)

    response = client.get("/v1/symbols")
    assert response.status_code == 200
    tickers = [row["ticker"] for row in response.json()]
    assert tickers == ["AAPL", "MSFT"]


def test_list_symbols_includes_inactive_when_asked(session: Session, client: TestClient) -> None:
    _seed_symbol(session, "OLD", name="Delisted", is_active=False)
    response = client.get("/v1/symbols", params={"active_only": "false"})
    assert response.status_code == 200
    assert [r["ticker"] for r in response.json()] == ["OLD"]


def test_get_symbol_returns_latest_quote(session: Session, client: TestClient) -> None:
    _seed_symbol(session, "AAPL", name="Apple")
    _seed_bar(session, "AAPL", datetime(2025, 4, 10), close="180.00")
    _seed_bar(session, "AAPL", datetime(2025, 4, 11), close="182.50")

    response = client.get("/v1/symbols/AAPL")
    assert response.status_code == 200
    body = response.json()
    assert body["ticker"] == "AAPL"
    # Numeric(18, 6) serializes with trailing zeros — that's the contract.
    assert body["latest"]["close"] == "182.500000"


def test_get_symbol_404_when_missing(client: TestClient) -> None:
    response = client.get("/v1/symbols/NOPE")
    assert response.status_code == 404


def test_get_symbol_is_case_insensitive(session: Session, client: TestClient) -> None:
    _seed_symbol(session, "AAPL", name="Apple")
    response = client.get("/v1/symbols/aapl")
    assert response.status_code == 200
    assert response.json()["ticker"] == "AAPL"


# ---------------------------------------------------------------------------
# /v1/symbols/{ticker}/bars
# ---------------------------------------------------------------------------


def test_bars_returns_chronological(session: Session, client: TestClient) -> None:
    _seed_symbol(session, "AAPL", name="Apple")
    for day in (10, 11, 12):
        _seed_bar(session, "AAPL", datetime(2025, 4, day), close=f"18{day}.00")

    response = client.get("/v1/symbols/AAPL/bars")
    assert response.status_code == 200
    bars = response.json()
    timestamps = [b["ts"] for b in bars]
    assert timestamps == sorted(timestamps)
    assert len(bars) == 3


def test_bars_range_filter(session: Session, client: TestClient) -> None:
    _seed_symbol(session, "AAPL", name="Apple")
    for day in (1, 2, 3, 4, 5):
        _seed_bar(session, "AAPL", datetime(2025, 4, day))

    response = client.get(
        "/v1/symbols/AAPL/bars",
        params={"from": "2025-04-02", "to": "2025-04-04"},
    )
    assert response.status_code == 200
    bars = response.json()
    assert len(bars) == 3
    # Returned in chronological order from the route.
    assert bars[0]["ts"].startswith("2025-04-02")
    assert bars[-1]["ts"].startswith("2025-04-04")


def test_bars_limit_returns_most_recent(session: Session, client: TestClient) -> None:
    _seed_symbol(session, "AAPL", name="Apple")
    for day in range(1, 11):
        _seed_bar(session, "AAPL", datetime(2025, 4, day))

    response = client.get("/v1/symbols/AAPL/bars", params={"limit": 3})
    assert response.status_code == 200
    bars = response.json()
    assert len(bars) == 3
    # The most-recent N, reversed to chronological order.
    assert [b["ts"][:10] for b in bars] == ["2025-04-08", "2025-04-09", "2025-04-10"]


def test_bars_404_when_symbol_missing(client: TestClient) -> None:
    response = client.get("/v1/symbols/NOPE/bars")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# /v1/news
# ---------------------------------------------------------------------------


def test_news_for_ticker(session: Session, client: TestClient) -> None:
    _seed_symbol(session, "AAPL", name="Apple")
    session.add_all(
        [
            NewsArticle(
                ticker="AAPL",
                title="Older",
                url="https://example.com/old",
                published_at=datetime(2025, 4, 10, 9, 0),
            ),
            NewsArticle(
                ticker="AAPL",
                title="Newer",
                url="https://example.com/new",
                published_at=datetime(2025, 4, 11, 9, 0),
            ),
        ]
    )
    session.commit()

    response = client.get("/v1/symbols/AAPL/news")
    assert response.status_code == 200
    titles = [a["title"] for a in response.json()]
    assert titles == ["Newer", "Older"]


# ---------------------------------------------------------------------------
# /v1/quotes
# ---------------------------------------------------------------------------


def test_batch_quotes(session: Session, client: TestClient) -> None:
    _seed_symbol(session, "AAPL", name="Apple")
    _seed_symbol(session, "MSFT", name="Microsoft")
    _seed_bar(session, "AAPL", datetime(2025, 4, 10), close="180.00")
    _seed_bar(session, "AAPL", datetime(2025, 4, 11), close="182.50")
    _seed_bar(session, "MSFT", datetime(2025, 4, 11), close="410.00")

    response = client.get("/v1/quotes", params={"tickers": "AAPL,MSFT"})
    assert response.status_code == 200
    body = {row["ticker"]: row["close"] for row in response.json()}
    assert body == {"AAPL": "182.500000", "MSFT": "410.000000"}


def test_batch_quotes_rejects_empty(client: TestClient) -> None:
    response = client.get("/v1/quotes", params={"tickers": ""})
    assert response.status_code == 400


def test_batch_quotes_rejects_too_many(client: TestClient) -> None:
    response = client.get("/v1/quotes", params={"tickers": ",".join(f"T{i}" for i in range(51))})
    assert response.status_code == 400
