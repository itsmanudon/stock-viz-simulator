"""Phase 5.3: fill rules, spread and slippage, fee schedules."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlmodel import Session

from stockviz.models import PriceBar
from stockviz.services.backtest import run_backtest
from stockviz.services.simulation import (
    LEGACY_CLOSE,
    LIVE_PAPER_EXECUTION_PROFILE,
    NEXT_OPEN,
    CostModel,
    FillStatus,
    MarketSnapshot,
    OrderIntent,
    OrderSide,
    SimulationOrderType,
    evaluate_order,
    get_execution_profile,
    get_fee_schedule,
)
from tests.symbols import seed_symbols

AT = datetime(2026, 11, 10, tzinfo=UTC)
BAR = MarketSnapshot(
    ticker="AAPL",
    observed_at=AT,
    interval="1d",
    open=Decimal("100"),
    high=Decimal("105"),
    low=Decimal("95"),
    close=Decimal("102"),
    volume=Decimal(1),
)


def _order(side: OrderSide, kind=SimulationOrderType.MARKET) -> OrderIntent:
    return OrderIntent(
        ticker="AAPL",
        side=side,
        order_type=kind,
        quantity=Decimal(10),
        remaining_quantity=Decimal(10),
        submitted_at=AT,
        limit_price=Decimal(101) if kind is not SimulationOrderType.MARKET else None,
    )


def test_next_open_fills_at_the_open_with_costs_against_the_trader() -> None:
    costs = CostModel(spread_bps=Decimal(10), slippage_bps=Decimal(5))  # 5 + 5 = 10 bps
    buy = evaluate_order(_order(OrderSide.BUY), BAR, NEXT_OPEN, costs)
    sell = evaluate_order(_order(OrderSide.SELL), BAR, NEXT_OPEN, costs)
    assert buy.fill_price == Decimal("100.100000")
    assert sell.fill_price == Decimal("99.900000")
    assert buy.trace.reference_price == Decimal("100")
    assert buy.trace.profile == "next_open" and "slippage 5 bps" in buy.trace.reason
    limit = evaluate_order(_order(OrderSide.BUY, SimulationOrderType.LIMIT), BAR, NEXT_OPEN)
    assert limit.status is FillStatus.INELIGIBLE


def test_live_paper_trading_is_unchanged() -> None:
    assert LIVE_PAPER_EXECUTION_PROFILE is LEGACY_CLOSE
    fill = evaluate_order(_order(OrderSide.BUY), BAR, LIVE_PAPER_EXECUTION_PROFILE)
    assert fill.fill_price == Decimal("102") and fill.trace.reference_price == Decimal("102")
    assert get_execution_profile("next_open", "v1") is NEXT_OPEN


def test_us_fee_schedule() -> None:
    us = get_fee_schedule("us_equity_2026")
    sell = us.fees(OrderSide.SELL, Decimal(1000), Decimal(150), commission_bps=Decimal(1))
    # Notional 150,000: commission 15.00, SEC 150,000 x 20.60 / 1e6 = 3.09,
    # TAF 1000 x 0.000195 = 0.195 -> 0.20.
    assert dict(sell.components) == {
        "commission": Decimal("15.000000"),
        "sec_section_31": Decimal("3.09"),
        "finra_taf": Decimal("0.20"),
    }
    capped = us.fees(OrderSide.SELL, Decimal(100_000), Decimal(1))
    assert dict(capped.components)["finra_taf"] == Decimal("9.79")
    assert us.fees(OrderSide.BUY, Decimal(1000), Decimal(150)).components == ()


def test_the_engine_fills_the_next_bar_at_its_open() -> None:
    days = [datetime(2024, 1, d) for d in range(1, 7)]
    closes = [Decimal(c) for c in (10, 10, 10, 30, 30, 60)]
    opens = dict(zip(days, [Decimal(o) for o in (10, 10, 10, 28, 31, 55)], strict=True))
    result = run_backtest(
        list(zip(days, closes, strict=True)),
        initial_cash=Decimal(1000),
        strategy_type="sma_crossover",
        params={"short_window": 2, "long_window": 3},
        opens=opens,
        fill_rule="next_open",
    )
    (buy,) = result.trades
    assert (buy.date.day, buy.price) == (5, Decimal("31"))  # signal Jan 4, filled Jan 5 open


def _seed(session: Session) -> None:
    seed_symbols(session, "AAPL")
    for i, (o, c) in enumerate(((10, 10), (10, 10), (10, 10), (30, 30), (31, 30), (60, 60))):
        session.add(
            PriceBar(
                ticker="AAPL",
                ts=datetime(2024, 1, 1) + timedelta(days=i),
                interval="1d",
                open=Decimal(o),
                high=Decimal(max(o, c)),
                low=Decimal(min(o, c)),
                close=Decimal(c),
                volume=1,
                source="test",
            )
        )
    session.commit()


def test_endpoint_defaults_to_next_open_and_reports_costs(
    session: Session, client: TestClient
) -> None:
    _seed(session)
    body = client.post(
        "/v1/backtest",
        json={
            "ticker": "AAPL",
            "from": "2024-01-01",
            "to": "2024-01-31",
            "initial_cash": "1000",
            "strategy": {"type": "sma_crossover", "short_window": 2, "long_window": 3},
            "spread_bps": 20,
            "commission_bps": 10,
            "fee_schedule": "us_equity_2026",
        },
    ).json()

    assert body["execution_profile"] == "next_open/v1"
    assert body["fee_schedule"] == "us_equity_2026"
    (buy,) = body["trades"]
    assert Decimal(buy["reference_price"]) == Decimal("31")  # Jan 5 open
    assert Decimal(buy["price"]) == Decimal("31.031000")  # + 10 bps (half the spread)
    assert [f["name"] for f in buy["fees"]] == ["commission"]  # SEC and TAF are sell-only
    costs = Decimal(body["summary"]["total_costs"])
    shares = Decimal(buy["shares"])
    assert costs == (shares * Decimal("0.031") + Decimal(buy["fees"][0]["amount"])).quantize(
        Decimal("0.000001")
    )
