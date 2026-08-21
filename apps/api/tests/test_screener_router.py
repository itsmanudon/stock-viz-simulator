"""HTTP-level tests for /v1/symbols/screen.

The fixtures here seed three contrasting tickers so each filter has at least
one match and one rejection in every test:

- UPUP  — monotonic uptrend, RSI saturates near 100, near 52-week high
- DOWN  — monotonic downtrend, RSI saturates near 0, near 52-week low
- FLAT  — flat close, RSI undefined (NaN), mid-range

``_seed_universe`` also runs ``refresh_symbol_metrics``: the screener queries
the materialized ``symbol_metrics`` table, which the daily scheduler job fills.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlmodel import Session

from stockviz.models import PriceBar, Symbol
from stockviz.services.metrics import refresh_symbol_metrics


def _seed_bars(
    session: Session,
    ticker: str,
    closes: list[Decimal],
    *,
    start: datetime = datetime(2025, 1, 1),
) -> None:
    for i, close in enumerate(closes):
        session.add(
            PriceBar(
                ticker=ticker,
                ts=start + timedelta(days=i),
                interval="1d",
                open=close,
                high=close,
                low=close,
                close=close,
                volume=1_000_000,
                source="test",
            )
        )


def _seed_universe(session: Session) -> None:
    session.add(Symbol(ticker="UPUP", name="Up Co", sector="Technology"))
    session.add(Symbol(ticker="DOWN", name="Down Co", sector="Technology"))
    session.add(Symbol(ticker="FLAT", name="Flat Co", sector="Utilities"))

    # 60 bars — enough for RSI(14) and a 30-day momentum window.
    _seed_bars(session, "UPUP", [Decimal(100 + i) for i in range(60)])
    _seed_bars(session, "DOWN", [Decimal(200 - i) for i in range(60)])
    _seed_bars(session, "FLAT", [Decimal(150) for _ in range(60)])

    session.commit()
    # The screener reads precomputed metrics rather than rescanning price_bars
    # on every request, so the fixture runs the refresh the scheduler would.
    refresh_symbol_metrics(session)


def test_screen_no_filters_returns_all(session: Session, client: TestClient) -> None:
    _seed_universe(session)
    response = client.get("/v1/symbols/screen")
    assert response.status_code == 200
    tickers = sorted(r["ticker"] for r in response.json())
    assert tickers == ["DOWN", "FLAT", "UPUP"]


def test_screen_sector_filter(session: Session, client: TestClient) -> None:
    _seed_universe(session)
    response = client.get("/v1/symbols/screen", params={"sector": "Utilities"})
    assert response.status_code == 200
    tickers = [r["ticker"] for r in response.json()]
    assert tickers == ["FLAT"]


def test_screen_rsi_overbought(session: Session, client: TestClient) -> None:
    _seed_universe(session)
    response = client.get("/v1/symbols/screen", params={"rsi_min": 70})
    assert response.status_code == 200
    tickers = sorted(r["ticker"] for r in response.json())
    # Monotonic uptrend → RSI = 100. Flat closes also pin to 100 by Wilder's
    # convention (avg_loss == 0). The falling series stays well below 70.
    assert "UPUP" in tickers
    assert "DOWN" not in tickers


def test_screen_rsi_oversold(session: Session, client: TestClient) -> None:
    _seed_universe(session)
    response = client.get("/v1/symbols/screen", params={"rsi_max": 30})
    assert response.status_code == 200
    tickers = [r["ticker"] for r in response.json()]
    assert tickers == ["DOWN"]


def test_screen_positive_momentum(session: Session, client: TestClient) -> None:
    _seed_universe(session)
    response = client.get(
        "/v1/symbols/screen",
        params={"momentum_days": 30, "momentum_min": 1},
    )
    assert response.status_code == 200
    body = response.json()
    tickers = [r["ticker"] for r in body]
    assert tickers == ["UPUP"]
    # 30 bars ago close was 100+(59-30)=129; today 159 → +30/129 ≈ 23.3%.
    assert body[0]["momentum_pct"] > 20


def test_screen_near_52w_high(session: Session, client: TestClient) -> None:
    _seed_universe(session)
    response = client.get("/v1/symbols/screen", params={"near_52w_high": "true"})
    assert response.status_code == 200
    tickers = [r["ticker"] for r in response.json()]
    # UPUP closes at its high; FLAT is at its high (constant); DOWN is far below.
    assert "UPUP" in tickers
    assert "FLAT" in tickers
    assert "DOWN" not in tickers


def test_screen_near_52w_low(session: Session, client: TestClient) -> None:
    _seed_universe(session)
    response = client.get("/v1/symbols/screen", params={"near_52w_low": "true"})
    assert response.status_code == 200
    tickers = [r["ticker"] for r in response.json()]
    assert "DOWN" in tickers
    assert "UPUP" not in tickers


def test_screen_combined_filters_and_logic(session: Session, client: TestClient) -> None:
    _seed_universe(session)
    response = client.get(
        "/v1/symbols/screen",
        params={
            "sector": "Technology",
            "rsi_min": 70,
            "momentum_days": 10,
            "momentum_min": 1,
            "near_52w_high": "true",
        },
    )
    assert response.status_code == 200
    tickers = [r["ticker"] for r in response.json()]
    assert tickers == ["UPUP"]


def test_screen_rejects_invalid_rsi(client: TestClient) -> None:
    response = client.get("/v1/symbols/screen", params={"rsi_min": 150})
    assert response.status_code == 422


def test_screen_skips_symbols_without_bars(session: Session, client: TestClient) -> None:
    session.add(Symbol(ticker="EMPTY", name="No bars"))
    _seed_universe(session)
    response = client.get("/v1/symbols/screen")
    assert response.status_code == 200
    tickers = [r["ticker"] for r in response.json()]
    assert "EMPTY" not in tickers
