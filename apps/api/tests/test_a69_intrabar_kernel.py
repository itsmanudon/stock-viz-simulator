"""A6.9: the ``intrabar_ohlc`` v1 profile and the bracket exit (``evaluate_oco_exit``).

Pure kernel tests on synthetic bars. The rules (design note M9.4):

- limits, stops and targets are judged on the bar's range with the open
  first, so a gap fills at the open;
- a stop and a target both inside one bar: the minute path decides; without
  one the stop fills first, labelled "order inside the bar unknown";
- live paper stays on ``legacy_close``; replay and backtests read the same
  registry.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from stockviz.services.backtest.engine import FILL_RULES
from stockviz.services.simulation import (
    BACKTEST_PROFILES,
    INTRABAR_OHLC,
    INTRABAR_UNKNOWN_LABEL,
    LEGACY_CLOSE,
    LIVE_PAPER_EXECUTION_PROFILE,
    NEXT_OPEN,
    REPLAY_PROFILES,
    FillStatus,
    MarketSnapshot,
    OrderIntent,
    OrderSide,
    SimulationOrderType,
    UnknownExecutionProfileError,
    evaluate_oco_exit,
    evaluate_order,
    evaluate_range_stop,
    get_execution_profile,
    replay_profile,
)

T0 = datetime(2025, 4, 9, tzinfo=UTC)
T1 = datetime(2025, 4, 10, tzinfo=UTC)
D = Decimal


def bar(o: str, h: str, lo: str, c: str, at: datetime = T1, interval: str = "1d"):
    return MarketSnapshot(ticker="AAPL", observed_at=at, interval=interval, open=D(o),
                          high=D(h), low=D(lo), close=D(c), volume=D(1000))  # fmt: skip


def intent(kind: SimulationOrderType, price: str, side: OrderSide = OrderSide.SELL) -> OrderIntent:
    return OrderIntent(ticker="AAPL", side=side, order_type=kind, quantity=D(5),
                       submitted_at=T0, limit_price=D(price))  # fmt: skip


STOP = intent(SimulationOrderType.STOP_LOSS, "95")
TARGET = intent(SimulationOrderType.TAKE_PROFIT, "110")


def minutes(*ohlc: tuple[str, str, str, str]) -> list[MarketSnapshot]:
    return [bar(*row, at=T1 + timedelta(minutes=i), interval="1m") for i, row in enumerate(ohlc)]


def test_registry_shares_profiles_and_live_stays_legacy() -> None:
    assert LIVE_PAPER_EXECUTION_PROFILE is LEGACY_CLOSE
    assert get_execution_profile("intrabar_ohlc", "v1") is INTRABAR_OHLC
    assert ("intrabar_ohlc", "v1") in REPLAY_PROFILES
    assert ("intrabar_ohlc", "v1") in BACKTEST_PROFILES
    assert replay_profile(None) is INTRABAR_OHLC  # the replay default since 27 Nov 2026
    assert replay_profile("legacy_close") is LEGACY_CLOSE
    assert replay_profile("intrabar_ohlc") is INTRABAR_OHLC
    with pytest.raises(UnknownExecutionProfileError):
        replay_profile("next_open")  # backtest-only
    with pytest.raises(UnknownExecutionProfileError):
        get_execution_profile("intrabar_ohlc", "v2")
    # The backtester's fill rules are registry objects too.
    for profile in FILL_RULES.values():
        assert get_execution_profile(profile.name, profile.model_version) is profile


@pytest.mark.parametrize(
    ("kind", "side", "level", "ohlc", "expected"),
    [
        # Buy limit: touched by the low fills at the limit; an open below fills at the open.
        (SimulationOrderType.LIMIT, OrderSide.BUY, "99", ("101", "104", "97", "100"), "99"),
        (SimulationOrderType.LIMIT, OrderSide.BUY, "99", ("98", "104", "97", "100"), "98"),
        (SimulationOrderType.LIMIT, OrderSide.BUY, "96", ("101", "104", "97", "100"), None),
        # Sell limit and target: the high; an open above fills at the open.
        (SimulationOrderType.LIMIT, OrderSide.SELL, "103", ("101", "104", "97", "100"), "103"),
        (
            SimulationOrderType.TAKE_PROFIT,
            OrderSide.SELL,
            "103",
            ("105", "106", "97", "100"),
            "105",
        ),
        (
            SimulationOrderType.TAKE_PROFIT,
            OrderSide.SELL,
            "105",
            ("101", "104", "97", "100"),
            None,
        ),
        # Sell stop: the low; a gap down fills at the open.
        (SimulationOrderType.STOP_LOSS, OrderSide.SELL, "98", ("101", "104", "97", "100"), "98"),
        (SimulationOrderType.STOP_LOSS, OrderSide.SELL, "98", ("96", "104", "95", "100"), "96"),
        (SimulationOrderType.STOP_LOSS, OrderSide.SELL, "96", ("101", "104", "97", "100"), None),
    ],
)
def test_intrabar_range_open_first(kind, side, level, ohlc, expected) -> None:
    decision = evaluate_order(intent(kind, level, side), bar(*ohlc), INTRABAR_OHLC)
    if expected is None:
        assert decision.status is FillStatus.NOT_TRIGGERED
        return
    assert decision.status is FillStatus.FILLED
    assert decision.fill_price == D(expected)
    assert decision.trace.profile == "intrabar_ohlc"


def test_intrabar_stop_equals_range_stop() -> None:
    """The backtester's range stop and the profile's stop are one rule."""
    for ohlc in (("101", "104", "97", "100"), ("96", "104", "95", "100"), ("101", "104", "99", "100")):  # fmt: skip
        stop = intent(SimulationOrderType.STOP_LOSS, "98")
        a = evaluate_order(stop, bar(*ohlc), INTRABAR_OHLC)
        b = evaluate_range_stop(stop, bar(*ohlc), INTRABAR_OHLC)
        assert (a.status, a.fill_price) == (b.status, b.fill_price)


def test_market_fills_at_close_and_legacy_unchanged() -> None:
    market = OrderIntent(ticker="AAPL", side=OrderSide.BUY, order_type=SimulationOrderType.MARKET,
                         quantity=D(1), submitted_at=T0)  # fmt: skip
    assert evaluate_order(market, bar("101", "104", "97", "100"), INTRABAR_OHLC).fill_price == D(
        "100"
    )
    # legacy_close still triggers on the close only: a low through the stop is ignored.
    legacy = evaluate_order(
        intent(SimulationOrderType.STOP_LOSS, "98"), bar("101", "104", "97", "100"), LEGACY_CLOSE
    )
    assert legacy.status is FillStatus.NOT_TRIGGERED


def test_oco_only_one_leg_in_reach() -> None:
    target = evaluate_oco_exit(STOP, TARGET, bar("100", "111", "96", "105"), INTRABAR_OHLC)
    assert (target.leg, target.decision.fill_price, target.basis) == ("target", D("110"), "bar")
    stop = evaluate_oco_exit(STOP, TARGET, bar("100", "109", "94", "96"), INTRABAR_OHLC)
    assert (stop.leg, stop.decision.fill_price, stop.basis) == ("stop", D("95"), "bar")
    neither = evaluate_oco_exit(STOP, TARGET, bar("100", "109", "96", "101"), INTRABAR_OHLC)
    assert neither.leg is None and neither.decision.status is FillStatus.NOT_TRIGGERED


def test_oco_gap_fills_at_the_open() -> None:
    """The open comes first: an open through the target (or stop) decides,
    even when the bar's range also reaches the other level."""
    up = evaluate_oco_exit(STOP, TARGET, bar("112", "113", "90", "100"), INTRABAR_OHLC)
    assert (up.leg, up.decision.fill_price, up.basis) == ("target", D("112"), "bar")
    down = evaluate_oco_exit(STOP, TARGET, bar("93", "120", "90", "100"), INTRABAR_OHLC)
    assert (down.leg, down.decision.fill_price, down.basis) == ("stop", D("93"), "bar")


def test_oco_both_inside_without_minutes_stop_first_labelled() -> None:
    result = evaluate_oco_exit(STOP, TARGET, bar("100", "111", "94", "105"), INTRABAR_OHLC)
    assert result.leg == "stop" and result.order_unknown
    assert result.decision.fill_price == D("95")
    assert result.decision.trace.reason.startswith(INTRABAR_UNKNOWN_LABEL)


def test_oco_both_inside_minutes_decide() -> None:
    daily = bar("100", "111", "94", "105")
    # The target is reached first in the minutes, the stop later.
    path = minutes(("100", "104", "99", "103"), ("103", "111", "102", "108"),
                   ("108", "108", "94", "96"))  # fmt: skip
    result = evaluate_oco_exit(STOP, TARGET, daily, INTRABAR_OHLC, path=path)
    assert (result.leg, result.decision.fill_price, result.basis) == ("target", D("110"), "minutes")
    assert INTRABAR_UNKNOWN_LABEL not in result.decision.trace.reason
    # The other order: the stop first.
    path = minutes(("100", "101", "94", "96"), ("96", "111", "96", "110"))
    result = evaluate_oco_exit(STOP, TARGET, daily, INTRABAR_OHLC, path=path)
    assert (result.leg, result.decision.fill_price, result.basis) == ("stop", D("95"), "minutes")
    # A minute that gaps through the stop fills at that minute's open.
    path = minutes(("100", "104", "99", "103"), ("93", "111", "92", "100"))
    result = evaluate_oco_exit(STOP, TARGET, daily, INTRABAR_OHLC, path=path)
    assert (result.leg, result.decision.fill_price) == ("stop", D("93"))


def test_oco_both_inside_one_minute_stop_first() -> None:
    path = minutes(("100", "111", "94", "100"))
    result = evaluate_oco_exit(STOP, TARGET, bar("100", "111", "94", "105"), INTRABAR_OHLC,
                               path=path)  # fmt: skip
    assert result.leg == "stop" and result.basis == "unknown"
    assert result.decision.trace.reason.startswith(INTRABAR_UNKNOWN_LABEL)
    assert "one stored minute" in result.decision.trace.reason


def test_oco_minutes_reaching_neither_fall_back_to_stop_first() -> None:
    path = minutes(("100", "101", "99", "100"))
    result = evaluate_oco_exit(STOP, TARGET, bar("100", "111", "94", "105"), INTRABAR_OHLC,
                               path=path)  # fmt: skip
    assert result.leg == "stop" and result.order_unknown


def test_oco_legacy_close_and_next_open() -> None:
    legacy = evaluate_oco_exit(STOP, TARGET, bar("100", "111", "94", "111"), LEGACY_CLOSE)
    assert (legacy.leg, legacy.decision.fill_price) == ("target", D("111"))
    legacy = evaluate_oco_exit(STOP, TARGET, bar("100", "111", "94", "100"), LEGACY_CLOSE)
    assert legacy.leg is None
    nope = evaluate_oco_exit(STOP, TARGET, bar("100", "111", "94", "100"), NEXT_OPEN)
    assert nope.leg is None and nope.decision.status is FillStatus.INELIGIBLE


def test_oco_rejects_wrong_legs() -> None:
    limit = intent(SimulationOrderType.LIMIT, "110")
    result = evaluate_oco_exit(STOP, limit, bar("100", "111", "94", "100"), INTRABAR_OHLC)
    assert result.decision.status is FillStatus.INELIGIBLE
