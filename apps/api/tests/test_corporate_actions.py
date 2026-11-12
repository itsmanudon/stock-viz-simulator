"""Splits rebase the ledger once (Phase 4.2, #65).

Stored closes are yfinance's split-adjusted series, rewritten nightly. Before
this, a 4-for-1 split divided every close by four while positions, orders,
alerts and option strikes stayed put, so the holding read as a 75% loss.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlmodel import Session, col, select

from stockviz.models import (
    Alert,
    AlertDirection,
    CorporateAction,
    CorporateActionApplication,
    OptionsPosition,
    OptionStatus,
    OptionType,
    OrderStatus,
    OrderType,
    PendingOrder,
    Position,
    Symbol,
    Trade,
    TradeSide,
    User,
)
from stockviz.services.corporate_actions.apply import apply_due_splits, cutoff
from stockviz.services.corporate_actions.splits import ledger_tickers, ratio_pair, record_splits
from stockviz.services.trading import ensure_default_portfolio

EX_DATE = date(2026, 8, 31)  # a Monday session
BEFORE = datetime(2026, 8, 20, 15)  # naive UTC, on the old scale
AFTER = datetime(2026, 9, 1, 1)  # after the ex-date bar completed
NOW = datetime(2026, 9, 1, 2, tzinfo=UTC)


def _user(session: Session, email: str = "split@stockviz.dev") -> tuple[int, int]:
    user = User(email=email, name="Splitter")
    session.add(user)
    session.commit()
    session.refresh(user)
    assert user.id is not None
    portfolio = ensure_default_portfolio(session, user.id)
    session.commit()
    assert portfolio.id is not None
    return user.id, portfolio.id


def _symbol(session: Session, ticker: str = "AAPL") -> None:
    if session.get(Symbol, ticker) is None:
        session.add(Symbol(ticker=ticker, name=ticker))
        session.commit()


def _split(session: Session, *, ex_date: date = EX_DATE, frm: str = "1", to: str = "4") -> None:
    session.add(
        CorporateAction(
            ticker="AAPL",
            kind="split",
            ex_date=ex_date,
            ratio_from=Decimal(frm),
            ratio_to=Decimal(to),
            source="test",
        )
    )
    session.commit()


def _trade(
    session: Session, portfolio_id: int, side: TradeSide, qty: str, price: str, ts: datetime
):
    session.add(
        Trade(
            portfolio_id=portfolio_id,
            ticker="AAPL",
            side=side,
            quantity=Decimal(qty),
            price=Decimal(price),
            ts=ts,
        )
    )


def _position(session: Session, portfolio_id: int, qty: str, avg: str) -> None:
    session.add(
        Position(
            portfolio_id=portfolio_id, ticker="AAPL", quantity=Decimal(qty), avg_cost=Decimal(avg)
        )
    )


@pytest.fixture
def book(session: Session) -> tuple[Session, int, int]:
    """10 shares bought at $200 before a 4-for-1 split, 8 at $50 after it."""

    _symbol(session)
    user_id, portfolio_id = _user(session)
    _trade(session, portfolio_id, TradeSide.BUY, "10", "200", BEFORE)
    _trade(session, portfolio_id, TradeSide.BUY, "8", "50", AFTER)
    _position(session, portfolio_id, "18", "133.333333")
    session.add_all(
        [
            PendingOrder(
                portfolio_id=portfolio_id,
                ticker="AAPL",
                side=TradeSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal("2"),
                limit_price=Decimal("150"),
                created_at=BEFORE,
            ),
            PendingOrder(
                portfolio_id=portfolio_id,
                ticker="AAPL",
                side=TradeSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal("4"),
                limit_price=Decimal("40"),
                created_at=AFTER,
            ),
            Alert(
                user_id=user_id,
                ticker="AAPL",
                direction=AlertDirection.ABOVE,
                target_price=Decimal("220"),
                created_at=BEFORE,
            ),
            Alert(
                user_id=user_id,
                ticker="AAPL",
                direction=AlertDirection.ABOVE,
                target_price=Decimal("210"),
                created_at=BEFORE,
                triggered_at=BEFORE,
            ),
            OptionsPosition(
                user_id=user_id,
                portfolio_id=portfolio_id,
                ticker="AAPL",
                option_type=OptionType.CALL,
                strike=Decimal("200"),
                expiry=date(2026, 12, 18),
                quantity=1,
                premium_paid=Decimal("500"),
                opened_at=BEFORE,
            ),
        ]
    )
    session.commit()
    return session, user_id, portfolio_id


def _snapshot(session: Session, portfolio_id: int, user_id: int):
    position = session.exec(
        select(Position).where(col(Position.portfolio_id) == portfolio_id)
    ).one()
    orders = session.exec(select(PendingOrder).order_by(col(PendingOrder.id))).all()
    alerts = session.exec(select(Alert).order_by(col(Alert.id))).all()
    option = session.exec(
        select(OptionsPosition).where(col(OptionsPosition.user_id) == user_id)
    ).one()
    return (
        (position.quantity, position.avg_cost),
        [(o.quantity, o.limit_price) for o in orders],
        [a.target_price for a in alerts],
        (option.strike, option.shares_per_contract),
    )


def test_cutoff_is_the_ex_date_bar_completing_on_the_venue() -> None:
    action = CorporateAction(
        ticker="AAPL",
        kind="split",
        ex_date=EX_DATE,
        ratio_from=Decimal(1),
        ratio_to=Decimal(4),
        source="t",
    )
    # 16:00 New York (EDT) is 20:00 UTC, plus the 45-minute completion margin.
    assert cutoff(action) == datetime(2026, 8, 31, 20, 45)


def test_split_rebases_only_the_old_scale(book) -> None:
    session, user_id, portfolio_id = book
    _split(session)

    result = apply_due_splits(session, now=NOW)

    assert (result.actions_due, result.users_rebased) == (1, 1)
    position, orders, alerts, option = _snapshot(session, portfolio_id, user_id)
    # 10 old shares become 40; the 8 bought after the split stay; cost $2,400 kept.
    assert position == (Decimal("48"), Decimal("50"))
    assert orders == [(Decimal("8"), Decimal("37.5")), (Decimal("4"), Decimal("40"))]
    assert alerts == [Decimal("55"), Decimal("210")]  # a triggered alert is history
    assert option == (Decimal("50"), Decimal("400"))


def test_rerun_changes_nothing(book) -> None:
    session, user_id, portfolio_id = book
    _split(session)
    apply_due_splits(session, now=NOW)
    first = _snapshot(session, portfolio_id, user_id)

    result = apply_due_splits(session, now=NOW)

    assert result.users_rebased == 0
    assert _snapshot(session, portfolio_id, user_id) == first
    assert len(session.exec(select(CorporateActionApplication)).all()) == 1


def test_a_split_before_the_ledger_existed_changes_nothing(book) -> None:
    session, user_id, portfolio_id = book
    before = _snapshot(session, portfolio_id, user_id)
    _split(session, ex_date=date(2020, 8, 31))

    result = apply_due_splits(session, now=NOW)

    assert result.users_rebased == 0
    assert _snapshot(session, portfolio_id, user_id) == before


def test_a_split_not_yet_complete_waits(book) -> None:
    session, user_id, portfolio_id = book
    before = _snapshot(session, portfolio_id, user_id)
    _split(session)

    # 18:00 UTC on the ex-date: New York has not closed.
    result = apply_due_splits(session, now=datetime(2026, 8, 31, 18, tzinfo=UTC))

    assert result.actions_due == 0
    assert _snapshot(session, portfolio_id, user_id) == before


def test_reverse_split(session: Session) -> None:
    _symbol(session)
    _user_id, portfolio_id = _user(session, "reverse@stockviz.dev")
    _trade(session, portfolio_id, TradeSide.BUY, "100", "2", BEFORE)
    _position(session, portfolio_id, "100", "2")
    session.commit()
    _split(session, frm="10", to="1")

    apply_due_splits(session, now=NOW)

    position = session.exec(select(Position)).one()
    assert (position.quantity, position.avg_cost) == (Decimal("10"), Decimal("20"))


def test_shares_sold_before_the_split_are_not_counted(session: Session) -> None:
    _symbol(session)
    _user_id, portfolio_id = _user(session, "seller@stockviz.dev")
    _trade(session, portfolio_id, TradeSide.BUY, "10", "200", BEFORE)
    _trade(session, portfolio_id, TradeSide.SELL, "4", "210", BEFORE)
    _position(session, portfolio_id, "6", "200")
    session.commit()
    _split(session, frm="1", to="2")

    apply_due_splits(session, now=NOW)

    position = session.exec(select(Position)).one()
    assert (position.quantity, position.avg_cost) == (Decimal("12"), Decimal("100"))


@pytest.mark.parametrize(
    ("ratio", "pair"),
    [
        (4.0, (Decimal(1), Decimal(4))),
        (0.1, (Decimal(10), Decimal(1))),
        (1.5, (Decimal(2), Decimal(3))),
        (0.0, None),
        (1.0, None),
        (float("nan"), None),
    ],
)
def test_ratio_pair(ratio: float, pair) -> None:
    assert ratio_pair(ratio) == pair


def test_record_splits_is_idempotent_and_keeps_an_applied_ratio(book) -> None:
    session, _user_id, _portfolio_id = book
    fetch = lambda _t: [(EX_DATE, 4.0), (date(2020, 8, 31), 4.0)]  # noqa: E731

    assert record_splits(session, "AAPL", fetch_fn=fetch) == 2
    session.commit()
    assert record_splits(session, "AAPL", fetch_fn=fetch) == 0

    apply_due_splits(session, now=NOW)
    assert record_splits(session, "AAPL", fetch_fn=lambda _t: [(EX_DATE, 2.0)]) == 0
    action = session.exec(
        select(CorporateAction).where(col(CorporateAction.ex_date) == EX_DATE)
    ).one()
    assert action.ratio_to == Decimal(4)


def test_ledger_tickers_lists_only_what_a_split_could_touch(book) -> None:
    session, _user_id, _portfolio_id = book
    _symbol(session, "MSFT")
    assert ledger_tickers(session) == ["AAPL"]


def test_option_value_follows_shares_per_contract(book) -> None:
    session, user_id, _portfolio_id = book
    _split(session)
    apply_due_splits(session, now=NOW)
    option = session.exec(
        select(OptionsPosition).where(col(OptionsPosition.user_id) == user_id)
    ).one()
    # Strike times deliverable is unchanged by the split: $200 x 100 = $50 x 400.
    assert option.strike * option.shares_per_contract == Decimal("20000")
    assert option.status == OptionStatus.OPEN
    assert session.exec(select(PendingOrder)).first().status == OrderStatus.PENDING  # type: ignore[union-attr]


def _bar(day: date, close: str, source: str):
    from stockviz.services.ingest.bar_semantics import AdjustmentSemantics, SessionScope
    from stockviz.services.ingest.prices import BarRecord

    value = Decimal(close)
    return BarRecord(
        ticker="AAPL",
        ts=datetime.combine(day, datetime.min.time()),
        interval="1d",
        open=value,
        high=value,
        low=value,
        close=value,
        volume=Decimal(1000),
        source=source,
        adjustment_semantics=AdjustmentSemantics.UNADJUSTED,
        session_scope=SessionScope.REGULAR,
    )


def test_alpha_vantage_fallback_only_adds_newer_days(session: Session) -> None:
    """Audit MD-5: the unadjusted fallback never overwrites adjusted history."""

    from stockviz.models import PriceBar
    from stockviz.services.ingest.prices import upsert_bars

    _symbol(session)
    upsert_bars(session, [_bar(date(2026, 9, 1), "50", "yfinance")])
    session.commit()

    written = upsert_bars(
        session,
        [
            _bar(date(2026, 9, 1), "200", "alpha_vantage"),
            _bar(date(2026, 9, 2), "51", "alpha_vantage"),
        ],
    )
    session.commit()

    assert written == 1
    rows = session.exec(select(PriceBar).order_by(col(PriceBar.ts))).all()
    assert [(r.ts.date(), r.close, r.source) for r in rows] == [
        (date(2026, 9, 1), Decimal("50"), "yfinance"),
        (date(2026, 9, 2), Decimal("51"), "alpha_vantage"),
    ]


def test_alpha_vantage_fills_an_empty_ticker(session: Session) -> None:
    from stockviz.services.ingest.prices import upsert_bars

    _symbol(session)
    bars = [
        _bar(date(2026, 9, 1), "50", "alpha_vantage"),
        _bar(date(2026, 9, 2), "51", "alpha_vantage"),
    ]
    assert upsert_bars(session, bars) == 2
