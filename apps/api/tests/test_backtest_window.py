"""Phase 5.2: the backtester on the kernel, with warm-up, currency and basis."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from stockviz.models import Dividend, PriceBar
from tests.symbols import seed_symbols

DAY0 = datetime(2024, 1, 1)


def _seed(
    session: Session,
    closes: list[float],
    *,
    ticker: str = "AAPL",
    currency: str = "USD",
    basis: list[str] | None = None,
) -> None:
    seed_symbols(session, ticker, currency=currency)
    for i, close in enumerate(closes):
        price = Decimal(str(close))
        session.add(
            PriceBar(
                ticker=ticker,
                ts=DAY0 + timedelta(days=i),
                interval="1d",
                open=price,
                high=price,
                low=price,
                close=price,
                volume=1000,
                source="test",
                adjustment_semantics=(basis[i] if basis else "split_adjusted"),
            )
        )
    session.commit()


def _run(client: TestClient, *, start: str, ticker: str = "AAPL", **extra) -> dict:
    response = client.post(
        "/v1/backtest",
        json={
            "ticker": ticker,
            "from": start,
            "to": "2024-01-31",
            "initial_cash": "1000",
            "strategy": {"type": "sma_crossover", "short_window": 2, "long_window": 3},
            **extra,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_the_strategy_warms_up_before_the_window(session: Session, client: TestClient) -> None:
    # Jan 1-3 at 10 are before the window; the window is Jan 4-6: 30, 30, 60.
    _seed(session, [10, 10, 10, 30, 30, 60])
    body = _run(client, start="2024-01-04")

    assert body["warmup_bars"] == 3
    # The cross on Jan 4 is only visible with the warm-up; it fills Jan 5 at 30.
    assert [(t["date"], t["side"], Decimal(t["price"])) for t in body["trades"]] == [
        ("2024-01-05", "buy", Decimal("30"))
    ]
    assert body["equity_curve"][0]["date"] == "2024-01-04"  # window only
    # Buy-and-hold starts on the window's first bar (30 -> 60), not the warm-up.
    assert body["summary"]["benchmark_return"] == pytest.approx(1.0)
    assert body["summary"]["total_return"] == pytest.approx(1.0, abs=1e-5)


def test_a_non_usd_run_names_its_currency(session: Session, client: TestClient) -> None:
    _seed(session, [100, 100, 100, 110], ticker="SAP.DE", currency="EUR")
    body = _run(client, start="2024-01-01", ticker="SAP.DE")
    assert body["currency"] == "EUR"


def test_price_basis_is_reported_and_mixed_is_named(session: Session, client: TestClient) -> None:
    _seed(
        session,
        [10, 10, 10, 30],
        basis=["split_adjusted", "split_adjusted", "unadjusted", "split_adjusted"],
    )
    body = _run(client, start="2024-01-01")
    assert body["price_basis"] == "mixed"
    assert body["return_mode"] == "price"


def test_total_return_credits_dividends_to_held_shares(
    session: Session, client: TestClient
) -> None:
    _seed(session, [10, 10, 10, 20, 20, 20])
    session.add(Dividend(ticker="AAPL", ex_date=date(2024, 1, 6), amount=Decimal("1")))
    session.commit()

    price_only = _run(client, start="2024-01-01")
    total = _run(client, start="2024-01-01", return_mode="total")

    # Bought on Jan 5 at 20 with 1000: 50 shares; the Jan 6 dividend pays 50.
    assert Decimal(total["summary"]["final_nav"]) - Decimal(
        price_only["summary"]["final_nav"]
    ) == Decimal("50")
    assert total["return_mode"] == "total"
    assert total["summary"]["benchmark_return"] > price_only["summary"]["benchmark_return"]
