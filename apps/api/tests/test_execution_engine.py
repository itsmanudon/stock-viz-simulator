"""Pure execution-kernel tests (SIM-01).

These pin ``legacy_close`` to current StockViz fill rules. They do not call
``execute_trade`` or ``settle_pending_orders`` and do not prove live paper
trading uses the kernel.
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from stockviz.models.order import OrderType
from stockviz.models.portfolio import TradeSide
from stockviz.services.simulation import (
    LEGACY_CLOSE,
    LEGACY_CLOSE_ASSUMPTIONS,
    LEGACY_CLOSE_MODEL_VERSION,
    LEGACY_CLOSE_NAME,
    LIVE_PAPER_EXECUTION_PROFILE,
    ExecutionProfile,
    FillDecision,
    FillStatus,
    MarketSnapshot,
    OrderIntent,
    OrderSide,
    SimulationClock,
    SimulationClockError,
    SimulationOrderType,
    UnknownExecutionProfileError,
    evaluate_order,
    get_execution_profile,
    is_legacy_close,
)

SIMULATION_ROOT = (
    Path(__file__).resolve().parents[1] / "src" / "stockviz" / "services" / "simulation"
)

SUBMITTED_AT = datetime(2026, 8, 26, 20, 0, tzinfo=UTC)
OBSERVED_AT = datetime(2026, 8, 26, 21, 0, tzinfo=UTC)
DEFAULT_QUANTITY = Decimal("10")

FORBIDDEN_IMPORT_PREFIXES = (
    "sqlmodel",
    "fastapi",
    "httpx",
    "apscheduler",
    "confluent_kafka",
    "yfinance",
    "redis",
    "stockviz.db",
    "stockviz.settings",
    "stockviz.scheduler",
    "stockviz.auth",
    "stockviz.events",
    "stockviz.workers",
    "stockviz.routers",
    "stockviz.services.trading",
    "stockviz.services.options",
    "stockviz.services.backtest",
    "stockviz.services.replay",
    "stockviz._time",
)


def _dec(value: str) -> Decimal:
    return Decimal(value)


def _snapshot(
    *,
    close: Decimal,
    ticker: str = "AAPL",
    observed_at: datetime = OBSERVED_AT,
    high: Decimal | None = None,
    low: Decimal | None = None,
    open_: Decimal | None = None,
    volume: Decimal | None = None,
    interval: str = "1d",
) -> MarketSnapshot:
    return MarketSnapshot(
        ticker=ticker,
        observed_at=observed_at,
        interval=interval,
        open=open_ if open_ is not None else close,
        high=high if high is not None else close,
        low=low if low is not None else close,
        close=close,
        volume=volume if volume is not None else _dec("1000000"),
    )


def _intent(
    *,
    side: OrderSide,
    order_type: SimulationOrderType,
    ticker: str = "AAPL",
    quantity: Decimal = DEFAULT_QUANTITY,
    remaining: Decimal | None = None,
    submitted_at: datetime = SUBMITTED_AT,
    limit_price: Decimal | None = None,
) -> OrderIntent:
    return OrderIntent(
        ticker=ticker,
        side=side,
        order_type=order_type,
        quantity=quantity,
        remaining_quantity=remaining,
        submitted_at=submitted_at,
        limit_price=limit_price,
    )


def _evaluate(
    order: OrderIntent,
    market: MarketSnapshot,
    profile: ExecutionProfile = LEGACY_CLOSE,
) -> FillDecision:
    return evaluate_order(order, market, profile)


def _legacy_pending_triggers(
    *,
    order_type: OrderType,
    side: TradeSide,
    limit_price: Decimal,
    close: Decimal,
) -> bool:
    """Historical ``_should_fill`` boolean, kept only to pin kernel parity."""

    if order_type == OrderType.LIMIT:
        return close <= limit_price if side == TradeSide.BUY else close >= limit_price
    if order_type == OrderType.STOP_LOSS:
        return close <= limit_price
    if order_type == OrderType.TAKE_PROFIT:
        return close >= limit_price
    return False


# --- MARKET -----------------------------------------------------------------


def test_market_buy_fills_at_close() -> None:
    close = _dec("184.12")
    decision = _evaluate(
        _intent(side=OrderSide.BUY, order_type=SimulationOrderType.MARKET),
        _snapshot(close=close),
    )
    assert decision.status is FillStatus.FILLED
    assert decision.fill_price == close
    assert decision.fill_quantity == _dec("10")
    assert decision.remaining_quantity == Decimal(0)


def test_market_sell_fills_at_close() -> None:
    close = _dec("50.00")
    decision = _evaluate(
        _intent(side=OrderSide.SELL, order_type=SimulationOrderType.MARKET),
        _snapshot(close=close),
    )
    assert decision.status is FillStatus.FILLED
    assert decision.fill_price == close


# --- LIMIT ------------------------------------------------------------------


def test_limit_buy_close_below_limit_fills() -> None:
    decision = _evaluate(
        _intent(side=OrderSide.BUY, order_type=SimulationOrderType.LIMIT, limit_price=_dec("100")),
        _snapshot(close=_dec("99.99")),
    )
    assert decision.status is FillStatus.FILLED
    assert decision.fill_price == _dec("99.99")


def test_limit_buy_close_equal_limit_fills() -> None:
    decision = _evaluate(
        _intent(side=OrderSide.BUY, order_type=SimulationOrderType.LIMIT, limit_price=_dec("100")),
        _snapshot(close=_dec("100")),
    )
    assert decision.status is FillStatus.FILLED
    assert decision.fill_price == _dec("100")


def test_limit_buy_close_above_limit_not_triggered() -> None:
    decision = _evaluate(
        _intent(side=OrderSide.BUY, order_type=SimulationOrderType.LIMIT, limit_price=_dec("100")),
        _snapshot(close=_dec("100.01")),
    )
    assert decision.status is FillStatus.NOT_TRIGGERED
    assert decision.fill_price is None
    assert decision.fill_quantity == Decimal(0)
    assert decision.remaining_quantity == _dec("10")


def test_limit_sell_close_above_limit_fills() -> None:
    decision = _evaluate(
        _intent(side=OrderSide.SELL, order_type=SimulationOrderType.LIMIT, limit_price=_dec("100")),
        _snapshot(close=_dec("100.01")),
    )
    assert decision.status is FillStatus.FILLED
    assert decision.fill_price == _dec("100.01")


def test_limit_sell_close_equal_limit_fills() -> None:
    decision = _evaluate(
        _intent(side=OrderSide.SELL, order_type=SimulationOrderType.LIMIT, limit_price=_dec("100")),
        _snapshot(close=_dec("100")),
    )
    assert decision.status is FillStatus.FILLED


def test_limit_sell_close_below_limit_not_triggered() -> None:
    decision = _evaluate(
        _intent(side=OrderSide.SELL, order_type=SimulationOrderType.LIMIT, limit_price=_dec("100")),
        _snapshot(close=_dec("99.99")),
    )
    assert decision.status is FillStatus.NOT_TRIGGERED


# --- STOP LOSS --------------------------------------------------------------


def test_stop_loss_sell_close_below_trigger_fills() -> None:
    decision = _evaluate(
        _intent(
            side=OrderSide.SELL, order_type=SimulationOrderType.STOP_LOSS, limit_price=_dec("100")
        ),
        _snapshot(close=_dec("99.50")),
    )
    assert decision.status is FillStatus.FILLED
    assert decision.fill_price == _dec("99.50")


def test_stop_loss_sell_equal_trigger_fills() -> None:
    decision = _evaluate(
        _intent(
            side=OrderSide.SELL, order_type=SimulationOrderType.STOP_LOSS, limit_price=_dec("100")
        ),
        _snapshot(close=_dec("100")),
    )
    assert decision.status is FillStatus.FILLED


def test_stop_loss_sell_above_trigger_not_triggered() -> None:
    decision = _evaluate(
        _intent(
            side=OrderSide.SELL, order_type=SimulationOrderType.STOP_LOSS, limit_price=_dec("100")
        ),
        _snapshot(close=_dec("100.01")),
    )
    assert decision.status is FillStatus.NOT_TRIGGERED


def test_unsupported_buy_stop_loss_is_ineligible() -> None:
    decision = _evaluate(
        _intent(
            side=OrderSide.BUY, order_type=SimulationOrderType.STOP_LOSS, limit_price=_dec("100")
        ),
        _snapshot(close=_dec("90")),
    )
    assert decision.status is FillStatus.INELIGIBLE
    assert "sell-only" in decision.trace.reason
    assert decision.fill_price is None


# --- TAKE PROFIT ------------------------------------------------------------


def test_take_profit_sell_above_target_fills() -> None:
    decision = _evaluate(
        _intent(
            side=OrderSide.SELL,
            order_type=SimulationOrderType.TAKE_PROFIT,
            limit_price=_dec("100"),
        ),
        _snapshot(close=_dec("101")),
    )
    assert decision.status is FillStatus.FILLED
    assert decision.fill_price == _dec("101")


def test_take_profit_sell_equal_target_fills() -> None:
    decision = _evaluate(
        _intent(
            side=OrderSide.SELL,
            order_type=SimulationOrderType.TAKE_PROFIT,
            limit_price=_dec("100"),
        ),
        _snapshot(close=_dec("100")),
    )
    assert decision.status is FillStatus.FILLED


def test_take_profit_sell_below_target_not_triggered() -> None:
    decision = _evaluate(
        _intent(
            side=OrderSide.SELL,
            order_type=SimulationOrderType.TAKE_PROFIT,
            limit_price=_dec("100"),
        ),
        _snapshot(close=_dec("99.99")),
    )
    assert decision.status is FillStatus.NOT_TRIGGERED


def test_unsupported_buy_take_profit_is_ineligible() -> None:
    decision = _evaluate(
        _intent(
            side=OrderSide.BUY,
            order_type=SimulationOrderType.TAKE_PROFIT,
            limit_price=_dec("100"),
        ),
        _snapshot(close=_dec("150")),
    )
    assert decision.status is FillStatus.INELIGIBLE
    assert "sell-only" in decision.trace.reason


# --- VALIDATION -------------------------------------------------------------


def test_zero_quantity_is_invalid() -> None:
    with pytest.raises(ValueError, match="quantity"):
        _intent(side=OrderSide.BUY, order_type=SimulationOrderType.MARKET, quantity=_dec("0"))


def test_negative_quantity_is_invalid() -> None:
    with pytest.raises(ValueError, match="quantity"):
        _intent(side=OrderSide.BUY, order_type=SimulationOrderType.MARKET, quantity=_dec("-1"))


def test_missing_limit_price_is_invalid() -> None:
    with pytest.raises(ValueError, match="limit_price"):
        _intent(side=OrderSide.BUY, order_type=SimulationOrderType.LIMIT)


def test_missing_stop_trigger_is_invalid() -> None:
    with pytest.raises(ValueError, match="limit_price"):
        _intent(side=OrderSide.SELL, order_type=SimulationOrderType.STOP_LOSS)


def test_ticker_mismatch_is_ineligible() -> None:
    decision = _evaluate(
        _intent(side=OrderSide.BUY, order_type=SimulationOrderType.MARKET, ticker="AAPL"),
        _snapshot(close=_dec("10"), ticker="MSFT"),
    )
    assert decision.status is FillStatus.INELIGIBLE
    assert "ticker" in decision.trace.reason.lower()
    assert decision.trace.reference_price is None


def test_remaining_greater_than_quantity_is_invalid() -> None:
    with pytest.raises(ValueError, match="remaining_quantity"):
        _intent(
            side=OrderSide.BUY,
            order_type=SimulationOrderType.MARKET,
            quantity=_dec("5"),
            remaining=_dec("6"),
        )


def test_pre_submission_snapshot_is_ineligible() -> None:
    submitted = datetime(2026, 8, 26, 18, 0, tzinfo=UTC)
    observed = datetime(2026, 8, 26, 17, 59, 59, tzinfo=UTC)
    decision = _evaluate(
        _intent(side=OrderSide.BUY, order_type=SimulationOrderType.MARKET, submitted_at=submitted),
        _snapshot(close=_dec("184.12"), observed_at=observed),
    )
    assert decision.status is FillStatus.INELIGIBLE
    assert "observed_at" in decision.trace.reason
    assert decision.fill_price is None
    assert decision.trace.reference_price is None


def test_snapshot_at_submission_instant_is_eligible() -> None:
    instant = datetime(2026, 8, 26, 20, 0, tzinfo=UTC)
    decision = _evaluate(
        _intent(side=OrderSide.BUY, order_type=SimulationOrderType.MARKET, submitted_at=instant),
        _snapshot(close=_dec("10"), observed_at=instant),
    )
    assert decision.status is FillStatus.FILLED


def test_naive_submitted_at_is_invalid() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        OrderIntent(
            ticker="AAPL",
            side=OrderSide.BUY,
            order_type=SimulationOrderType.MARKET,
            quantity=_dec("1"),
            submitted_at=datetime(2026, 8, 26, 20, 0),
        )


def test_empty_ticker_is_invalid() -> None:
    with pytest.raises(ValueError, match="ticker"):
        _intent(side=OrderSide.BUY, order_type=SimulationOrderType.MARKET, ticker="  ")


def test_order_intent_rejects_raw_side_string() -> None:
    with pytest.raises(TypeError, match="OrderSide"):
        OrderIntent(
            ticker="AAPL",
            side="buy",  # type: ignore[arg-type]
            order_type=SimulationOrderType.MARKET,
            quantity=_dec("1"),
            submitted_at=SUBMITTED_AT,
        )


def test_order_intent_rejects_raw_order_type_string() -> None:
    with pytest.raises(TypeError, match="SimulationOrderType"):
        OrderIntent(
            ticker="AAPL",
            side=OrderSide.BUY,
            order_type="market",  # type: ignore[arg-type]
            quantity=_dec("1"),
            submitted_at=SUBMITTED_AT,
        )


def test_order_intent_rejects_arbitrary_invalid_side() -> None:
    with pytest.raises(TypeError, match="OrderSide"):
        OrderIntent(
            ticker="AAPL",
            side="long",  # type: ignore[arg-type]
            order_type=SimulationOrderType.MARKET,
            quantity=_dec("1"),
            submitted_at=SUBMITTED_AT,
        )


def test_order_intent_rejects_arbitrary_invalid_order_type() -> None:
    with pytest.raises(TypeError, match="SimulationOrderType"):
        OrderIntent(
            ticker="AAPL",
            side=OrderSide.BUY,
            order_type="stop",  # type: ignore[arg-type]
            quantity=_dec("1"),
            submitted_at=SUBMITTED_AT,
        )


def test_order_intent_accepts_enum_members() -> None:
    order = OrderIntent(
        ticker="AAPL",
        side=OrderSide.BUY,
        order_type=SimulationOrderType.MARKET,
        quantity=_dec("1"),
        submitted_at=SUBMITTED_AT,
    )
    assert order.side is OrderSide.BUY
    assert order.order_type is SimulationOrderType.MARKET


def test_unknown_profile_is_ineligible() -> None:
    decision = _evaluate(
        _intent(side=OrderSide.BUY, order_type=SimulationOrderType.MARKET),
        _snapshot(close=_dec("10")),
        ExecutionProfile(name="ideal", model_version="v1", assumptions=()),
    )
    assert decision.status is FillStatus.INELIGIBLE
    assert "not implemented" in decision.trace.reason


def test_legacy_close_singleton_is_recognized() -> None:
    assert is_legacy_close(LEGACY_CLOSE)
    decision = _evaluate(
        _intent(side=OrderSide.BUY, order_type=SimulationOrderType.MARKET),
        _snapshot(close=_dec("10")),
        LEGACY_CLOSE,
    )
    assert decision.status is FillStatus.FILLED
    assert decision.trace.profile == LEGACY_CLOSE_NAME
    assert decision.trace.model_version == LEGACY_CLOSE_MODEL_VERSION
    assert decision.trace.assumptions == LEGACY_CLOSE_ASSUMPTIONS


def test_canonical_equal_legacy_close_clone_is_recognized() -> None:
    clone = ExecutionProfile(
        name=LEGACY_CLOSE_NAME,
        model_version=LEGACY_CLOSE_MODEL_VERSION,
        assumptions=LEGACY_CLOSE_ASSUMPTIONS,
    )
    assert clone == LEGACY_CLOSE
    assert is_legacy_close(clone)
    decision = _evaluate(
        _intent(side=OrderSide.BUY, order_type=SimulationOrderType.MARKET),
        _snapshot(close=_dec("10")),
        clone,
    )
    assert decision.status is FillStatus.FILLED
    assert decision.trace.assumptions == LEGACY_CLOSE_ASSUMPTIONS
    assert decision.trace.assumptions is LEGACY_CLOSE_ASSUMPTIONS


def test_same_name_version_with_different_assumptions_is_not_legacy_close() -> None:
    spoofed = ExecutionProfile(
        name=LEGACY_CLOSE_NAME,
        model_version=LEGACY_CLOSE_MODEL_VERSION,
        assumptions=("Uses bid/ask mid",),
    )
    assert not is_legacy_close(spoofed)
    decision = _evaluate(
        _intent(side=OrderSide.BUY, order_type=SimulationOrderType.MARKET),
        _snapshot(close=_dec("10")),
        spoofed,
    )
    assert decision.status is FillStatus.INELIGIBLE
    assert decision.fill_price is None
    assert "not implemented" in decision.trace.reason


def test_spoofed_legacy_profile_cannot_publish_custom_assumptions_on_a_fill() -> None:
    spoofed = ExecutionProfile(
        name=LEGACY_CLOSE_NAME,
        model_version=LEGACY_CLOSE_MODEL_VERSION,
        assumptions=("Uses bid/ask mid", "Custom slippage"),
    )
    decision = _evaluate(
        _intent(side=OrderSide.BUY, order_type=SimulationOrderType.MARKET),
        _snapshot(close=_dec("184.12")),
        spoofed,
    )
    assert decision.status is FillStatus.INELIGIBLE
    assert decision.fill_quantity == Decimal(0)
    assert decision.fill_price is None
    assert decision.trace.assumptions == ("Uses bid/ask mid", "Custom slippage")
    assert decision.trace.assumptions != LEGACY_CLOSE_ASSUMPTIONS
    assert "Market order fills at observable daily close" not in decision.trace.reason


# --- DETERMINISM ------------------------------------------------------------


def test_identical_inputs_return_equal_decisions() -> None:
    order = _intent(
        side=OrderSide.BUY, order_type=SimulationOrderType.LIMIT, limit_price=_dec("100")
    )
    market = _snapshot(close=_dec("99.5"))
    first = _evaluate(order, market)
    second = _evaluate(order, market)
    assert first == second
    assert first.trace == second.trace


# --- DECIMAL ----------------------------------------------------------------


def test_fill_preserves_decimal_precision() -> None:
    close = _dec("184.123456")
    decision = _evaluate(
        _intent(side=OrderSide.BUY, order_type=SimulationOrderType.MARKET, quantity=_dec("2.5")),
        _snapshot(close=close),
    )
    assert type(decision.fill_price) is Decimal
    assert type(decision.fill_quantity) is Decimal
    assert decision.fill_price == close
    assert decision.fill_quantity == _dec("2.5")
    assert decision.fill_price == Decimal("184.123456")


def test_snapshot_rejects_float_prices() -> None:
    with pytest.raises(TypeError, match="float"):
        MarketSnapshot(
            ticker="AAPL",
            observed_at=OBSERVED_AT,
            interval="1d",
            open=_dec("1"),
            high=_dec("1"),
            low=_dec("1"),
            close=184.12,  # type: ignore[arg-type]
            volume=_dec("1"),
        )


def test_order_intent_rejects_float_quantity() -> None:
    with pytest.raises(TypeError, match="float"):
        OrderIntent(
            ticker="AAPL",
            side=OrderSide.BUY,
            order_type=SimulationOrderType.MARKET,
            quantity=1.5,  # type: ignore[arg-type]
            submitted_at=SUBMITTED_AT,
        )


# --- TRACE ------------------------------------------------------------------


def test_fill_trace_explains_profile_and_reason() -> None:
    decision = _evaluate(
        _intent(side=OrderSide.BUY, order_type=SimulationOrderType.MARKET),
        _snapshot(close=_dec("184.12")),
    )
    assert decision.trace.profile == LEGACY_CLOSE_NAME
    assert decision.trace.model_version == LEGACY_CLOSE_MODEL_VERSION
    assert decision.trace.reference_price == _dec("184.12")
    assert decision.trace.fill_price == _dec("184.12")
    assert "daily close" in decision.trace.reason.lower()
    assert decision.trace.assumptions == LEGACY_CLOSE_ASSUMPTIONS


def test_non_trigger_trace_explains_why() -> None:
    decision = _evaluate(
        _intent(side=OrderSide.BUY, order_type=SimulationOrderType.LIMIT, limit_price=_dec("100")),
        _snapshot(close=_dec("101")),
    )
    assert decision.status is FillStatus.NOT_TRIGGERED
    assert "does not trigger" in decision.trace.reason
    assert decision.trace.fill_price is None
    assert decision.trace.reference_price == _dec("101")
    assert decision.trace.profile == LEGACY_CLOSE_NAME
    assert decision.trace.model_version == LEGACY_CLOSE_MODEL_VERSION
    assert decision.trace.assumptions == LEGACY_CLOSE_ASSUMPTIONS


# --- IMMUTABILITY -----------------------------------------------------------


def test_domain_contracts_are_frozen() -> None:
    order = _intent(side=OrderSide.BUY, order_type=SimulationOrderType.MARKET)
    market = _snapshot(close=_dec("10"))
    decision = _evaluate(order, market)
    with pytest.raises(FrozenInstanceError):
        order.quantity = _dec("99")  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        market.close = _dec("1")  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        decision.status = FillStatus.INELIGIBLE  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        decision.trace.reason = "mutated"  # type: ignore[misc]


# --- OHLC TOUCH MUST NOT FILL -----------------------------------------------


def test_legacy_close_ignores_intraday_low_for_limit_buy() -> None:
    """Daily low would have touched the limit before a close-only model may fill."""

    decision = _evaluate(
        _intent(side=OrderSide.BUY, order_type=SimulationOrderType.LIMIT, limit_price=_dec("100")),
        _snapshot(close=_dec("101"), low=_dec("99"), high=_dec("102")),
    )
    assert decision.status is FillStatus.NOT_TRIGGERED


def test_legacy_close_ignores_intraday_high_for_limit_sell() -> None:
    decision = _evaluate(
        _intent(side=OrderSide.SELL, order_type=SimulationOrderType.LIMIT, limit_price=_dec("100")),
        _snapshot(close=_dec("99"), low=_dec("98"), high=_dec("101")),
    )
    assert decision.status is FillStatus.NOT_TRIGGERED


# --- PARITY WITH CURRENT TRADING --------------------------------------------


def test_legacy_close_market_matches_current_market_fill_semantics() -> None:
    """``execute_trade`` fills at ``latest_bar.close`` via ``resolve_priced_symbol``."""

    close = _dec("184.12")
    decision = _evaluate(
        _intent(side=OrderSide.BUY, order_type=SimulationOrderType.MARKET),
        _snapshot(close=close),
    )
    assert decision.status is FillStatus.FILLED
    assert decision.fill_price == close
    assert decision.fill_quantity == _dec("10")
    assert decision.remaining_quantity == Decimal(0)


@pytest.mark.parametrize(
    ("close", "expect_fill"),
    [
        ("99.99", True),
        ("100", True),
        ("100.01", False),
    ],
)
def test_legacy_close_limit_buy_matches_pending_order_semantics(
    close: str, expect_fill: bool
) -> None:
    limit_price = _dec("100")
    close_price = _dec(close)
    current = _legacy_pending_triggers(
        order_type=OrderType.LIMIT, side=TradeSide.BUY, limit_price=limit_price, close=close_price
    )
    assert current is expect_fill
    decision = _evaluate(
        _intent(side=OrderSide.BUY, order_type=SimulationOrderType.LIMIT, limit_price=limit_price),
        _snapshot(close=close_price),
    )
    assert (decision.status is FillStatus.FILLED) is expect_fill
    if expect_fill:
        assert decision.fill_price == close_price
    else:
        assert decision.status is FillStatus.NOT_TRIGGERED


@pytest.mark.parametrize(
    ("close", "expect_fill"),
    [
        ("100.01", True),
        ("100", True),
        ("99.99", False),
    ],
)
def test_legacy_close_limit_sell_matches_pending_order_semantics(
    close: str, expect_fill: bool
) -> None:
    limit_price = _dec("100")
    close_price = _dec(close)
    current = _legacy_pending_triggers(
        order_type=OrderType.LIMIT, side=TradeSide.SELL, limit_price=limit_price, close=close_price
    )
    assert current is expect_fill
    decision = _evaluate(
        _intent(side=OrderSide.SELL, order_type=SimulationOrderType.LIMIT, limit_price=limit_price),
        _snapshot(close=close_price),
    )
    assert (decision.status is FillStatus.FILLED) is expect_fill
    if expect_fill:
        assert decision.fill_price == close_price
    else:
        assert decision.status is FillStatus.NOT_TRIGGERED


@pytest.mark.parametrize(
    ("close", "expect_fill"),
    [
        ("99.99", True),
        ("100", True),
        ("100.01", False),
    ],
)
def test_legacy_close_stop_loss_matches_pending_order_semantics(
    close: str, expect_fill: bool
) -> None:
    trigger = _dec("100")
    close_price = _dec(close)
    current = _legacy_pending_triggers(
        order_type=OrderType.STOP_LOSS, side=TradeSide.SELL, limit_price=trigger, close=close_price
    )
    assert current is expect_fill
    decision = _evaluate(
        _intent(side=OrderSide.SELL, order_type=SimulationOrderType.STOP_LOSS, limit_price=trigger),
        _snapshot(close=close_price),
    )
    assert (decision.status is FillStatus.FILLED) is expect_fill
    if expect_fill:
        assert decision.fill_price == close_price


@pytest.mark.parametrize(
    ("close", "expect_fill"),
    [
        ("100.01", True),
        ("100", True),
        ("99.99", False),
    ],
)
def test_legacy_close_take_profit_matches_pending_order_semantics(
    close: str, expect_fill: bool
) -> None:
    target = _dec("100")
    close_price = _dec(close)
    current = _legacy_pending_triggers(
        order_type=OrderType.TAKE_PROFIT, side=TradeSide.SELL, limit_price=target, close=close_price
    )
    assert current is expect_fill
    decision = _evaluate(
        _intent(
            side=OrderSide.SELL, order_type=SimulationOrderType.TAKE_PROFIT, limit_price=target
        ),
        _snapshot(close=close_price),
    )
    assert (decision.status is FillStatus.FILLED) is expect_fill
    if expect_fill:
        assert decision.fill_price == close_price


def test_legacy_close_fills_remaining_quantity_not_original() -> None:
    decision = _evaluate(
        _intent(
            side=OrderSide.BUY,
            order_type=SimulationOrderType.MARKET,
            quantity=_dec("10"),
            remaining=_dec("4"),
        ),
        _snapshot(close=_dec("20")),
    )
    assert decision.fill_quantity == _dec("4")
    assert decision.remaining_quantity == Decimal(0)


# --- PROFILE REGISTRY (SIM-04) ---------------------------------------------


def test_registry_returns_canonical_legacy_close() -> None:
    profile = get_execution_profile(LEGACY_CLOSE_NAME, LEGACY_CLOSE_MODEL_VERSION)
    assert profile is LEGACY_CLOSE
    assert profile is LIVE_PAPER_EXECUTION_PROFILE
    assert profile.assumptions == LEGACY_CLOSE_ASSUMPTIONS
    assert is_legacy_close(profile)


def test_registry_unknown_name_does_not_fall_back() -> None:
    with pytest.raises(UnknownExecutionProfileError, match="retail_realistic"):
        get_execution_profile("retail_realistic", LEGACY_CLOSE_MODEL_VERSION)


def test_registry_unknown_version_does_not_fall_back() -> None:
    with pytest.raises(UnknownExecutionProfileError, match="v2"):
        get_execution_profile(LEGACY_CLOSE_NAME, "v2")


# --- SIMULATION CLOCK (SIM-05) ---------------------------------------------


def test_simulation_clock_requires_aware_datetime() -> None:
    with pytest.raises(SimulationClockError, match="timezone-aware"):
        SimulationClock(now=datetime(2024, 1, 2, 21, 0, 0))


def test_simulation_clock_normalizes_to_utc() -> None:
    from datetime import timedelta, timezone

    eastern = timezone(timedelta(hours=-5))
    clock = SimulationClock(now=datetime(2024, 1, 2, 16, 0, tzinfo=eastern))
    assert clock.instant() == datetime(2024, 1, 2, 21, 0, tzinfo=UTC)


def test_simulation_clock_refuses_to_move_backwards() -> None:
    clock = SimulationClock(now=datetime(2024, 1, 2, tzinfo=UTC))
    with pytest.raises(SimulationClockError, match="backwards"):
        clock.advance_to(datetime(2024, 1, 1, tzinfo=UTC))


def test_simulation_clock_advance_equal_returns_same() -> None:
    instant = datetime(2024, 1, 2, 21, 0, tzinfo=UTC)
    clock = SimulationClock(now=instant)
    assert clock.advance_to(instant) is clock


def test_simulation_clock_permits_current_and_past_not_future() -> None:
    clock = SimulationClock(now=datetime(2024, 1, 2, 21, 0, tzinfo=UTC))
    assert clock.permits(datetime(2024, 1, 2, 21, 0, tzinfo=UTC))
    assert clock.permits(datetime(2024, 1, 2, 20, 0, tzinfo=UTC))
    assert not clock.permits(datetime(2024, 1, 2, 21, 0, 1, tzinfo=UTC))


# --- IMPORT BOUNDARY --------------------------------------------------------


def _imported_modules(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    return names


def test_simulation_package_has_no_infrastructure_imports() -> None:
    py_files = sorted(SIMULATION_ROOT.glob("*.py"))
    assert py_files, f"expected simulation package at {SIMULATION_ROOT}"
    violations: list[str] = []
    for path in py_files:
        for name in _imported_modules(path):
            if any(
                name == prefix or name.startswith(f"{prefix}.")
                for prefix in FORBIDDEN_IMPORT_PREFIXES
            ):
                violations.append(f"{path.name}: {name}")
    assert violations == []


def test_simulation_source_has_no_clock_or_rng() -> None:
    banned = ("datetime.now", "utcnow", "random.random", "random.Random", "time.time")
    hits: list[str] = []
    for path in SIMULATION_ROOT.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        for token in banned:
            if token in text:
                hits.append(f"{path.name}: {token}")
    assert hits == []


def test_fresh_import_does_not_load_infrastructure() -> None:
    script = """
import sys
import stockviz.services.simulation  # noqa: F401
forbidden = (
    "sqlmodel",
    "fastapi",
    "apscheduler",
    "confluent_kafka",
    "stockviz.db",
    "stockviz.settings",
    "stockviz.scheduler",
    "stockviz.events",
    "stockviz.workers",
    "stockviz.routers",
    "stockviz.services.trading",
)
loaded = [name for name in forbidden if name in sys.modules]
if loaded:
    raise SystemExit("loaded forbidden modules: " + ", ".join(loaded))
"""
    src = Path(__file__).resolve().parents[1] / "src"
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join([str(src), env.get("PYTHONPATH", "")])
    result = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        cwd=str(Path(__file__).resolve().parents[1]),
    )
    assert result.returncode == 0, result.stderr + result.stdout
