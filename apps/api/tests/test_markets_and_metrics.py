"""Tests for /v1/markets/summary and the precomputed symbol_metrics table.

Both exist to remove per-symbol work from a request path: the markets page used
to make one backend call per symbol, and the screener rescanned ~260 bars per
symbol on every request.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from stockviz.models import PriceBar, Symbol, SymbolMetrics
from stockviz.services.metrics import refresh_symbol_metrics, set_sentiment

_START = datetime(2025, 1, 1)


def _seed(session: Session, ticker: str, closes: list[Decimal], *, sector: str = "Technology"):
    session.add(Symbol(ticker=ticker, name=f"{ticker} Co", sector=sector, exchange="NASDAQ"))
    for i, close in enumerate(closes):
        session.add(
            PriceBar(
                ticker=ticker,
                ts=_START + timedelta(days=i),
                interval="1d",
                open=close,
                high=close,
                low=close,
                close=close,
                volume=1_000,
                source="test",
            )
        )
    session.commit()


# ---------------------------------------------------------------------------
# /v1/markets/summary
# ---------------------------------------------------------------------------


def test_summary_returns_rows_sparklines_and_sectors(session: Session, client: TestClient) -> None:
    _seed(session, "AAA", [Decimal(10), Decimal(11), Decimal(12)])
    _seed(session, "BBB", [Decimal(50), Decimal(45)], sector="Utilities")

    response = client.get("/v1/markets/summary?sparkline_days=30")
    assert response.status_code == 200
    body = response.json()

    assert body["sectors"] == ["Technology", "Utilities"]
    rows = {r["ticker"]: r for r in body["rows"]}
    assert set(rows) == {"AAA", "BBB"}

    aaa = rows["AAA"]
    assert Decimal(aaa["last_close"]) == Decimal(12)
    assert Decimal(aaa["prev_close"]) == Decimal(11)
    # 11 -> 12 is +9.0909...%
    assert abs(aaa["change_pct"] - 9.0909) < 0.001
    # Sparkline is oldest-first.
    assert [Decimal(c) for c in aaa["closes"]] == [Decimal(10), Decimal(11), Decimal(12)]

    assert rows["BBB"]["change_pct"] < 0


def test_summary_sector_filter_keeps_the_full_sector_list(
    session: Session, client: TestClient
) -> None:
    """Filtering rows must not shrink the filter control's options."""
    _seed(session, "AAA", [Decimal(10), Decimal(11)])
    _seed(session, "BBB", [Decimal(50), Decimal(45)], sector="Utilities")

    body = client.get("/v1/markets/summary?sector=Utilities").json()
    assert [r["ticker"] for r in body["rows"]] == ["BBB"]
    assert body["sectors"] == ["Technology", "Utilities"]


def test_summary_handles_a_symbol_with_no_bars(session: Session, client: TestClient) -> None:
    session.add(Symbol(ticker="NEW", name="Newly Listed", sector="Technology"))
    session.commit()

    body = client.get("/v1/markets/summary").json()
    row = next(r for r in body["rows"] if r["ticker"] == "NEW")
    assert row["last_close"] is None
    assert row["change_pct"] is None
    assert row["closes"] == []


def test_summary_sparkline_days_caps_the_series(session: Session, client: TestClient) -> None:
    _seed(session, "LONG", [Decimal(100 + i) for i in range(50)])
    body = client.get("/v1/markets/summary?sparkline_days=5").json()
    row = next(r for r in body["rows"] if r["ticker"] == "LONG")
    assert len(row["closes"]) == 5
    # Still the most recent five, oldest-first.
    assert [Decimal(c) for c in row["closes"]] == [Decimal(n) for n in (145, 146, 147, 148, 149)]


# ---------------------------------------------------------------------------
# symbol_metrics
# ---------------------------------------------------------------------------


def test_refresh_computes_rsi_and_52w_range(session: Session) -> None:
    _seed(session, "UPUP", [Decimal(100 + i) for i in range(60)])

    assert refresh_symbol_metrics(session) == 1
    row = session.get(SymbolMetrics, "UPUP")
    assert row is not None
    assert row.last_close == Decimal(159)
    assert row.high_52w == Decimal(159)
    assert row.low_52w == Decimal(100)
    # A monotonic uptrend saturates RSI near 100.
    assert row.rsi_14 is not None and row.rsi_14 > 90
    assert row.as_of == (_START + timedelta(days=59)).date()


def test_refresh_is_idempotent(session: Session) -> None:
    _seed(session, "AAA", [Decimal(10), Decimal(11), Decimal(12)])
    refresh_symbol_metrics(session)
    refresh_symbol_metrics(session)

    rows = session.exec(select(SymbolMetrics)).all()
    assert len(rows) == 1


def test_refresh_skips_symbols_without_bars(session: Session) -> None:
    session.add(Symbol(ticker="EMPTY", name="No Bars"))
    session.commit()
    assert refresh_symbol_metrics(session) == 0
    assert session.get(SymbolMetrics, "EMPTY") is None


def test_refresh_preserves_sentiment_columns(session: Session) -> None:
    """Metrics and sentiment are refreshed on different cadences — neither
    pass may clobber the other's columns."""
    _seed(session, "AAA", [Decimal(10), Decimal(11), Decimal(12)])
    refresh_symbol_metrics(session)
    set_sentiment(session, ticker="AAA", mean_score=0.42, article_count=7)
    session.commit()

    refresh_symbol_metrics(session)
    row = session.get(SymbolMetrics, "AAA")
    assert row is not None
    assert row.sentiment_7d == 0.42
    assert row.sentiment_article_count == 7


def test_screener_filters_on_sentiment(session: Session, client: TestClient) -> None:
    _seed(session, "GOOD", [Decimal(100 + i) for i in range(30)])
    _seed(session, "MEH", [Decimal(100) for _ in range(30)])
    refresh_symbol_metrics(session)
    set_sentiment(session, ticker="GOOD", mean_score=0.8, article_count=5)
    set_sentiment(session, ticker="MEH", mean_score=-0.6, article_count=5)
    session.commit()

    body = client.get("/v1/symbols/screen", params={"sentiment_min": 0.5}).json()
    assert [r["ticker"] for r in body] == ["GOOD"]
    assert body[0]["sentiment_7d"] == 0.8
