"""Phase 9.3: multi-leg strategies from templates, opened and closed as a unit."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from stockviz.models import (
    OptionCover,
    OptionSide,
    OptionsPosition,
    OptionStatus,
    OptionStrategy,
    OptionType,
    StrategyKind,
)
from stockviz.services.options import OptionTradeError, close_option, settle_expired_options
from stockviz.services.options.margin import LegSpec, same_expiry_risk
from stockviz.services.options.strategies import (
    close_strategy,
    open_strategy,
    plan_legs,
    quote_strategy,
)
from stockviz.services.trading import DEFAULT_STARTING_CASH, ensure_default_portfolio
from stockviz.services.trading.buying_power import available_cash, available_shares
from tests.test_option_short_legs import PRICES, _hold
from tests.test_options import EXPIRY_SESSION, TODAY, _auth_headers, _make_user, _seed_bars

D = Decimal
EXPIRY = TODAY + timedelta(days=30)
FAR = TODAY + timedelta(days=90)


@pytest.fixture(autouse=True)
def option_clock(monkeypatch):
    monkeypatch.setattr("stockviz.services.options.trade.utcnow", lambda: datetime(2026, 8, 24, 18))


def _account(session: Session, *, shares: int = 0) -> tuple[int, int]:
    _seed_bars(session, PRICES, end=TODAY - timedelta(days=1))  # spot 104
    user_id = _make_user(session)
    portfolio = ensure_default_portfolio(session, user_id)
    assert portfolio.id is not None
    if shares:
        _hold(session, portfolio.id, shares)
    return user_id, portfolio.id


def _open(session: Session, user_id: int, kind: StrategyKind, strikes: list[str], **kw):
    return open_strategy(
        session,
        user_id=user_id,
        kind=kind,
        ticker="AAPL",
        strikes=[D(k) for k in strikes],
        expiry=kw.pop("expiry", EXPIRY),
        quantity=kw.pop("quantity", 1),
        **kw,
    )


def _cash(session: Session, user_id: int) -> Decimal:
    return ensure_default_portfolio(session, user_id).cash_balance


# ---------------------------------------------------------------------------
# Templates and the maths
# ---------------------------------------------------------------------------


def test_templates_check_their_strikes() -> None:
    with pytest.raises(OptionTradeError, match="takes 2 strike"):
        plan_legs(StrategyKind.BULL_CALL, strikes=[D(100)], expiry=EXPIRY)
    with pytest.raises(OptionTradeError, match="low to high"):
        plan_legs(StrategyKind.BULL_CALL, strikes=[D(110), D(100)], expiry=EXPIRY)
    with pytest.raises(OptionTradeError, match="far expiry"):
        plan_legs(
            StrategyKind.CALENDAR, strikes=[D(100)], expiry=EXPIRY, option_type=OptionType.CALL
        )
    condor = plan_legs(
        StrategyKind.IRON_CONDOR, strikes=[D(90), D(95), D(105), D(110)], expiry=EXPIRY
    )
    assert [(p.side, p.option_type, p.strike, p.covered_by) for p in condor] == [
        (OptionSide.LONG, OptionType.PUT, D(90), None),
        (OptionSide.SHORT, OptionType.PUT, D(95), 0),
        (OptionSide.LONG, OptionType.CALL, D(110), None),
        (OptionSide.SHORT, OptionType.CALL, D(105), 2),
    ]
    assert all(p.covered_by is None or p.covered_by < i for i, p in enumerate(condor))


def test_an_uncovered_short_call_is_refused_by_the_maths() -> None:
    naked = [LegSpec("short", "call", D(110), D(100), D(2))]
    with pytest.raises(ValueError, match="not covered"):
        same_expiry_risk(naked, basis="x")


def test_a_bull_call_quote_matches_its_legs(session: Session) -> None:
    _account(session)
    q = quote_strategy(
        session, kind=StrategyKind.BULL_CALL, ticker="AAPL", strikes=[D(100), D(110)],
        expiry=EXPIRY, quantity=2,
    )  # fmt: skip
    (_, long_q), (_, short_q) = q.legs
    debit = long_q.premium - short_q.premium
    assert q.risk.net_premium == -debit
    assert q.risk.collateral == D(0)  # the long call covers the short one
    assert q.risk.max_loss == debit
    assert q.risk.max_gain == D(10) * 200 - debit
    (breakeven,) = q.risk.breakevens
    assert breakeven == (D(100) + debit / 200).quantize(D("0.01"))


# ---------------------------------------------------------------------------
# Opening: every leg or none
# ---------------------------------------------------------------------------


def test_a_bull_call_spread_opens_both_legs_and_pays_the_debit(session: Session) -> None:
    user_id, _ = _account(session)
    result = _open(session, user_id, StrategyKind.BULL_CALL, ["100", "110"])
    long_leg, short_leg = result.legs
    assert (long_leg.side, long_leg.cover) == (OptionSide.LONG, None)
    assert (short_leg.side, short_leg.cover) == (OptionSide.SHORT, OptionCover.LEG)
    assert short_leg.covering_leg_id == long_leg.id
    assert result.cash_delta < 0
    assert _cash(session, user_id) == DEFAULT_STARTING_CASH + result.cash_delta
    assert result.strategy.collateral == D(0)


def test_a_credit_spread_holds_back_its_width(session: Session) -> None:
    user_id, _ = _account(session)
    result = _open(session, user_id, StrategyKind.BEAR_CALL, ["100", "110"])
    credit = result.cash_delta
    assert credit > 0
    assert result.strategy.collateral == D(1000)  # (110 - 100) x 100
    portfolio = ensure_default_portfolio(session, user_id)
    assert portfolio.cash_balance == DEFAULT_STARTING_CASH + credit
    assert available_cash(session, portfolio) == DEFAULT_STARTING_CASH + credit - D(1000)


def test_an_iron_condor_holds_back_its_wider_side(session: Session) -> None:
    user_id, _ = _account(session)
    result = _open(session, user_id, StrategyKind.IRON_CONDOR, ["90", "95", "105", "115"])
    assert result.strategy.collateral == D(1000)  # the call side is 10 wide, the put side 5
    assert [leg.cover for leg in result.legs] == [None, "leg", None, "leg"]
    assert result.strategy.max_loss == D(1000) - result.cash_delta


def test_a_strategy_the_account_cannot_pay_opens_nothing(session: Session) -> None:
    user_id, _ = _account(session)
    portfolio = ensure_default_portfolio(session, user_id)
    portfolio.cash_balance = D(500)
    session.add(portfolio)
    session.commit()
    from stockviz.services.options import InsufficientCashForOption

    with pytest.raises(InsufficientCashForOption):
        _open(session, user_id, StrategyKind.BEAR_CALL, ["100", "110"])  # holds back 1,000
    session.rollback()
    assert session.exec(select(OptionsPosition)).first() is None
    assert session.exec(select(OptionStrategy)).first() is None
    assert _cash(session, user_id) == D(500)


def test_covered_call_and_protective_put_templates_need_the_shares(session: Session) -> None:
    from stockviz.services.options import InsufficientCoverForOption

    user_id, portfolio_id = _account(session, shares=100)
    _open(session, user_id, StrategyKind.COVERED_CALL, ["110"])
    assert available_shares(session, portfolio_id, "AAPL") == D(0)
    with pytest.raises(InsufficientCoverForOption, match="protects 200"):
        _open(session, user_id, StrategyKind.PROTECTIVE_PUT, ["95"], quantity=2)
    session.rollback()
    put = _open(session, user_id, StrategyKind.PROTECTIVE_PUT, ["95"])
    assert put.legs[0].side == OptionSide.LONG


def test_calendars_need_cash_only_for_a_put(session: Session) -> None:
    user_id, _ = _account(session)
    call = _open(
        session, user_id, StrategyKind.CALENDAR, ["105"], far_expiry=FAR,
        option_type=OptionType.CALL,
    )  # fmt: skip
    far_leg, near_leg = call.legs
    assert (far_leg.expiry, near_leg.expiry) == (FAR, EXPIRY)
    assert near_leg.covering_leg_id == far_leg.id
    assert call.strategy.collateral == D(0)
    put = _open(
        session, user_id, StrategyKind.CALENDAR, ["105"], far_expiry=FAR,
        option_type=OptionType.PUT,
    )  # fmt: skip
    # K (1 - e^(-r t)): 105 x 100 x (1 - e^(-0.05 x 60/365)) = 85.947..., rounded up.
    assert put.strategy.collateral == D("85.95")


def test_a_repeated_key_opens_the_strategy_once(session: Session) -> None:
    user_id, _ = _account(session)
    first = _open(session, user_id, StrategyKind.STRADDLE, ["105"], client_order_id="k-1")
    again = _open(session, user_id, StrategyKind.STRADDLE, ["105"], client_order_id="k-1")
    assert again.strategy.id == first.strategy.id
    assert len(session.exec(select(OptionsPosition)).all()) == 2


def test_the_single_order_limit_checks_the_most_it_can_lose(
    session: Session, client: TestClient
) -> None:
    user_id, _ = _account(session)
    client.put(
        "/v1/portfolio/limits", headers=_auth_headers(user_id), json={"max_order_pct": "0.5"}
    )
    from stockviz.services.risk.limits import LimitBreached

    with pytest.raises(LimitBreached, match="strategy's most loss"):
        _open(session, user_id, StrategyKind.BEAR_CALL, ["100", "120"])  # can lose ~2,000 > 500


def test_opening_at_model_prices_leaves_the_account_value_unchanged(
    session: Session, client: TestClient
) -> None:
    user_id, _ = _account(session)
    before = client.get("/v1/portfolio", headers=_auth_headers(user_id)).json()
    _open(session, user_id, StrategyKind.IRON_CONDOR, ["90", "95", "105", "115"])
    after = client.get("/v1/portfolio", headers=_auth_headers(user_id)).json()
    assert D(after["total_value"]) == pytest.approx(D(before["total_value"]), abs=D("0.05"))


# ---------------------------------------------------------------------------
# Closing
# ---------------------------------------------------------------------------


def test_closing_a_strategy_closes_every_leg_once(session: Session) -> None:
    user_id, _ = _account(session)
    opened = _open(session, user_id, StrategyKind.BEAR_CALL, ["100", "110"])
    cash_open = _cash(session, user_id)
    closed = close_strategy(session, user_id=user_id, strategy_id=opened.strategy.id)  # type: ignore[arg-type]
    assert closed.strategy.status == "closed"
    assert all(leg.status == OptionStatus.CLOSED for leg in closed.legs)
    assert _cash(session, user_id) == cash_open + closed.cash_delta
    realized = sum((leg.realized_pnl or D(0)) for leg in closed.legs)
    assert realized == opened.cash_delta + closed.cash_delta
    with pytest.raises(OptionTradeError, match="already closed"):
        close_strategy(session, user_id=user_id, strategy_id=opened.strategy.id)  # type: ignore[arg-type]


def test_a_long_leg_covering_a_short_one_cannot_be_closed_alone(session: Session) -> None:
    user_id, _ = _account(session)
    opened = _open(session, user_id, StrategyKind.BULL_PUT, ["95", "105"])
    long_leg, short_leg = opened.legs
    with pytest.raises(OptionTradeError, match="buy the short leg back first"):
        close_option(session, user_id=user_id, option_id=long_leg.id)  # type: ignore[arg-type]
    session.rollback()
    close_option(session, user_id=user_id, option_id=short_leg.id)  # type: ignore[arg-type]
    close_option(session, user_id=user_id, option_id=long_leg.id)  # type: ignore[arg-type]
    session.refresh(opened.strategy)
    assert opened.strategy.status == "closed"


# ---------------------------------------------------------------------------
# Expiry
# ---------------------------------------------------------------------------


def _expired_spread(session: Session, *, with_close: bool = True):
    if with_close:
        _seed_bars(session, [120.0], end=EXPIRY_SESSION)
    else:
        _seed_bars(session, [120.0], end=EXPIRY_SESSION - timedelta(days=3))
    user_id = _make_user(session)
    portfolio = ensure_default_portfolio(session, user_id)
    assert portfolio.id is not None
    strategy = OptionStrategy(
        user_id=user_id, portfolio_id=portfolio.id, kind="bull_call", net_premium=D(-400),
    )  # fmt: skip
    session.add(strategy)
    session.flush()
    long_leg = OptionsPosition(
        user_id=user_id, portfolio_id=portfolio.id, ticker="AAPL", option_type=OptionType.CALL,
        strike=D(100), expiry=TODAY - timedelta(days=1), quantity=1, premium_paid=D(600),
        strategy_id=strategy.id,
    )  # fmt: skip
    session.add(long_leg)
    session.flush()
    session.add(
        OptionsPosition(
            user_id=user_id, portfolio_id=portfolio.id, ticker="AAPL",
            option_type=OptionType.CALL, strike=D(110), expiry=TODAY - timedelta(days=1),
            quantity=1, premium_paid=D(200), side=OptionSide.SHORT, cover=OptionCover.LEG,
            covering_leg_id=long_leg.id, strategy_id=strategy.id,
        )
    )  # fmt: skip
    session.commit()
    return strategy


def test_a_spread_waits_while_its_expiry_close_is_missing(session: Session) -> None:
    strategy = _expired_spread(session, with_close=False)
    assert settle_expired_options(session, settle_date=TODAY) == 0
    assert all(p.status == OptionStatus.OPEN for p in session.exec(select(OptionsPosition)))
    session.refresh(strategy)
    assert strategy.status == "open"


def test_a_spread_settles_once(session: Session) -> None:
    strategy = _expired_spread(session)
    assert settle_expired_options(session, settle_date=TODAY) == 2
    assert settle_expired_options(session, settle_date=TODAY) == 0
    session.refresh(strategy)
    assert strategy.status == "settled"
    from stockviz.models import Notification

    (note,) = session.exec(select(Notification)).all()
    assert note.title == "Bull call spread settled"
    assert "net +1,000.00 USD" in note.body


def _calendar(session: Session, near_close: float):
    _seed_bars(session, [near_close], end=EXPIRY_SESSION)
    user_id = _make_user(session)
    portfolio = ensure_default_portfolio(session, user_id)
    assert portfolio.id is not None
    strategy = OptionStrategy(
        user_id=user_id, portfolio_id=portfolio.id, kind="calendar", net_premium=D(-150),
    )  # fmt: skip
    session.add(strategy)
    session.flush()
    far = OptionsPosition(
        user_id=user_id, portfolio_id=portfolio.id, ticker="AAPL", option_type=OptionType.CALL,
        strike=D(105), expiry=TODAY + timedelta(days=60), quantity=1, premium_paid=D(450),
        strategy_id=strategy.id,
    )  # fmt: skip
    session.add(far)
    session.flush()
    near = OptionsPosition(
        user_id=user_id, portfolio_id=portfolio.id, ticker="AAPL", option_type=OptionType.CALL,
        strike=D(105), expiry=TODAY - timedelta(days=1), quantity=1, premium_paid=D(300),
        side=OptionSide.SHORT, cover=OptionCover.LEG, covering_leg_id=far.id,
        strategy_id=strategy.id,
    )  # fmt: skip
    session.add(near)
    session.commit()
    return portfolio.id, strategy, far, near


def test_an_out_of_the_money_calendar_keeps_its_far_leg(session: Session) -> None:
    _, strategy, far, near = _calendar(session, 100.0)
    assert settle_expired_options(session, settle_date=TODAY) == 1
    session.refresh(near)
    session.refresh(far)
    session.refresh(strategy)
    assert (near.status, near.realized_pnl) == (OptionStatus.EXPIRED, D(300))
    assert far.status == OptionStatus.OPEN
    assert strategy.status == "open"


def test_an_in_the_money_calendar_sells_its_far_leg_to_pay(session: Session) -> None:
    portfolio_id, strategy, far, near = _calendar(session, 120.0)
    from stockviz.models import Portfolio

    before = session.get(Portfolio, portfolio_id).cash_balance  # type: ignore[union-attr]
    assert settle_expired_options(session, settle_date=TODAY) == 2
    for row in (near, far, strategy):
        session.refresh(row)
    assert (near.status, near.proceeds) == (OptionStatus.EXERCISED, D(-1500))
    assert far.status == OptionStatus.CLOSED
    # The far call is worth at least the 15.00 a share the near one owes.
    assert far.proceeds is not None and far.proceeds >= D(1500)
    after = session.get(Portfolio, portfolio_id).cash_balance  # type: ignore[union-attr]
    assert after == before - D(1500) + far.proceeds
    assert strategy.status == "settled"


def test_a_one_leg_strategy_settles_and_is_marked_settled(session: Session) -> None:
    _seed_bars(session, [120.0], end=EXPIRY_SESSION)
    user_id = _make_user(session)
    portfolio = ensure_default_portfolio(session, user_id)
    assert portfolio.id is not None
    _hold(session, portfolio.id, 100)
    strategy = OptionStrategy(
        user_id=user_id, portfolio_id=portfolio.id, kind="covered_call", net_premium=D(300),
    )  # fmt: skip
    session.add(strategy)
    session.flush()
    session.add(
        OptionsPosition(
            user_id=user_id, portfolio_id=portfolio.id, ticker="AAPL",
            option_type=OptionType.CALL, strike=D(110), expiry=TODAY - timedelta(days=1),
            quantity=1, premium_paid=D(300), side=OptionSide.SHORT, cover=OptionCover.SHARES,
            strategy_id=strategy.id,
        )
    )  # fmt: skip
    session.commit()
    assert settle_expired_options(session, settle_date=TODAY) == 1
    session.refresh(strategy)
    assert strategy.status == "settled"


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


def test_strategy_endpoints(session: Session, client: TestClient) -> None:
    user_id, _ = _account(session)
    body = {
        "kind": "iron_condor", "ticker": "AAPL", "strikes": ["90", "95", "105", "115"],
        "expiry": EXPIRY.isoformat(), "quantity": 1,
    }  # fmt: skip
    quote = client.post("/v1/options/strategies/quote", json=body)
    assert quote.status_code == 200, quote.text
    q = quote.json()
    assert q["label"] == "Iron condor"
    assert [leg["side"] for leg in q["legs"]] == ["long", "short", "long", "short"]
    assert D(q["risk"]["collateral"]) == D(1000)
    assert len(q["risk"]["breakevens"]) == 2

    opened = client.post("/v1/options/strategies", headers=_auth_headers(user_id), json=body)
    assert opened.status_code == 201, opened.text
    strategy = opened.json()["strategy"]
    assert strategy["status"] == "open" and len(strategy["legs"]) == 4
    assert {leg["strategy_id"] for leg in strategy["legs"]} == {strategy["id"]}

    listed = client.get("/v1/options/strategies", headers=_auth_headers(user_id)).json()
    assert [s["id"] for s in listed] == [strategy["id"]]

    closed = client.post(
        f"/v1/options/strategies/{strategy['id']}/close", headers=_auth_headers(user_id)
    )
    assert closed.status_code == 200, closed.text
    assert closed.json()["strategy"]["status"] == "closed"

    bad = client.post(
        "/v1/options/strategies/quote", json={**body, "strikes": ["95", "90", "105", "115"]}
    )
    assert bad.status_code == 400
    naked = client.post(
        "/v1/options/strategies",
        headers=_auth_headers(user_id),
        json={"kind": "covered_call", "ticker": "AAPL", "strikes": ["110"],
              "expiry": EXPIRY.isoformat(), "quantity": 1},
    )  # fmt: skip
    assert naked.status_code == 422  # no shares to cover it
