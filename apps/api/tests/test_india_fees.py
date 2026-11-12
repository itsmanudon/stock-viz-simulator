"""Phase 5.6: Indian equity delivery fees (Zerodha, read 12 Nov 2026)."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlmodel import Session

from stockviz.models import PriceBar
from stockviz.services.simulation import OrderSide, get_fee_schedule
from tests.symbols import seed_symbols


def test_nse_delivery_buy_and_sell_by_hand() -> None:
    nse = get_fee_schedule("in_delivery_nse_2026")
    buy = dict(nse.fees(OrderSide.BUY, Decimal(100), Decimal(2500)).components)
    assert buy == {
        "stt": Decimal("250"),
        "exchange_transaction": Decimal("7.68"),  # 0.00307% of 2,50,000 = 7.675
        "sebi": Decimal("0.25"),  # Rs 10 per crore
        "gst": Decimal("1.43"),  # 18% of (0 + 7.68 + 0.25)
        "stamp_duty": Decimal("37.50"),  # 0.015%, buys only
    }
    sell = nse.fees(OrderSide.SELL, Decimal(100), Decimal(2500))
    assert dict(sell.components)["dp_charge"] == Decimal("15.34")
    assert "stamp_duty" not in dict(sell.components)
    assert sell.total == Decimal("274.70")
    bse = dict(
        get_fee_schedule("in_delivery_bse_2026")
        .fees(OrderSide.BUY, Decimal(100), Decimal(2500))
        .components
    )
    assert bse["exchange_transaction"] == Decimal("9.38")  # 0.00375%


def test_brokerage_if_set_is_taxed() -> None:
    nse = get_fee_schedule("in_delivery_nse_2026")
    parts = dict(
        nse.fees(OrderSide.BUY, Decimal(100), Decimal(2500), commission_bps=Decimal(3)).components
    )
    assert parts["brokerage"] == Decimal("75.00")
    assert parts["gst"] == Decimal("14.93")  # 18% of (75 + 7.68 + 0.25)


def _seed(session: Session, ticker: str, currency: str) -> None:
    seed_symbols(session, ticker, currency=currency)
    for i, close in enumerate((100, 100, 100, 300, 300, 600)):
        price = Decimal(close)
        session.add(
            PriceBar(
                ticker=ticker,
                ts=datetime(2024, 1, 1) + timedelta(days=i),
                interval="1d",
                open=price,
                high=price,
                low=price,
                close=price,
                volume=1,
                source="test",
            )
        )
    session.commit()


def _run(client: TestClient, ticker: str, schedule: str):
    return client.post(
        "/v1/backtest",
        json={
            "ticker": ticker,
            "from": "2024-01-01",
            "to": "2024-01-31",
            "initial_cash": "100000",
            "strategy": {"type": "sma_crossover", "short_window": 2, "long_window": 3},
            "fee_schedule": schedule,
        },
    )


def test_an_indian_backtest_charges_indian_fees(session: Session, client: TestClient) -> None:
    _seed(session, "RELIANCE.NS", "INR")
    body = _run(client, "RELIANCE.NS", "in_delivery_nse_2026").json()
    assert body["currency"] == "INR" and body["fee_schedule"] == "in_delivery_nse_2026"
    (buy,) = body["trades"]
    assert {f["name"] for f in buy["fees"]} >= {"stt", "stamp_duty", "gst"}


def test_a_schedule_for_another_market_is_refused(session: Session, client: TestClient) -> None:
    _seed(session, "RELIANCE.NS", "INR")
    _seed(session, "AAPL", "USD")
    wrong = _run(client, "RELIANCE.NS", "us_equity_2026")
    assert wrong.status_code == 400 and "USD" in wrong.json()["detail"]
    assert _run(client, "AAPL", "in_delivery_nse_2026").status_code == 400
    assert _run(client, "AAPL", "none").status_code == 200
