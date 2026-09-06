"""Trading Journal: session dating, aggregation, options realization, isolation.

The aggregation tests build :class:`JournalExecution` values directly, because
the folds are pure — that keeps the edge cases (scratch trades, empty months,
week clipping, decimal precision) readable and independent of the ledger. The
router tests go through the real tables so ownership filtering and the
UTC → New York attribution are exercised end to end.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from itertools import pairwise

from fastapi.testclient import TestClient
from jose import jwt as jose_jwt
from sqlmodel import Session

from stockviz.models import (
    OptionsPosition,
    OptionStatus,
    OptionType,
    PortfolioSnapshot,
    Recommendation,
    Symbol,
    Trade,
    TradeSide,
    User,
)
from stockviz.services.journal import (
    ExecutionKind,
    JournalExecution,
    build_month,
    month_bounds,
    session_date,
    summarize,
    week_spans,
)
from stockviz.services.journal.query import utc_window
from stockviz.services.trading import ensure_default_portfolio
from stockviz.settings import get_settings

SECRET = get_settings().internal_api_token


def _auth_headers(user_id: int) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {jose_jwt.encode({'sub': str(user_id)}, SECRET, algorithm='HS256')}"
    }


def _make_user(session: Session, email: str) -> int:
    user = User(email=email, name="Journalist")
    session.add(user)
    session.commit()
    session.refresh(user)
    assert user.id is not None
    return user.id


def _seed_symbol(session: Session, ticker: str = "AAPL", currency: str = "USD") -> None:
    if session.get(Symbol, ticker) is None:
        session.add(Symbol(ticker=ticker, name=f"{ticker} Inc.", currency=currency))
        session.commit()


def _execution(
    *,
    day: date,
    pnl: str,
    ticker: str = "AAPL",
    reference_id: int = 1,
    hour: int = 15,
) -> JournalExecution:
    return JournalExecution(
        kind=ExecutionKind.EQUITY,
        reference_id=reference_id,
        ticker=ticker,
        session_date=day,
        executed_at=datetime.combine(day, datetime.min.time()) + timedelta(hours=hour),
        realized_pnl=Decimal(pnl),
    )


# ---------------------------------------------------------------------------
# Session dating
# ---------------------------------------------------------------------------


def test_late_utc_fill_belongs_to_the_previous_new_york_session() -> None:
    # 01:30 UTC on Aug 20 is 21:30 on Aug 19 in New York.
    assert session_date(datetime(2026, 8, 20, 1, 30)) == date(2026, 8, 19)


def test_early_utc_fill_belongs_to_the_same_new_york_session() -> None:
    # 20:00 UTC on Aug 19 is 16:00 the same day in New York.
    assert session_date(datetime(2026, 8, 19, 20, 0)) == date(2026, 8, 19)


def test_session_date_uses_the_eastern_offset_in_force_that_day() -> None:
    # 04:30 UTC. In March (EDT, UTC-4) that is 00:30 the same day; in January
    # (EST, UTC-5) it is 23:30 the day before. A fixed offset gets one wrong.
    assert session_date(datetime(2026, 3, 20, 4, 30)) == date(2026, 3, 20)
    assert session_date(datetime(2026, 1, 20, 4, 30)) == date(2026, 1, 19)


def test_utc_window_brackets_the_month_in_new_york_terms() -> None:
    start, end = utc_window(date(2026, 8, 1), date(2026, 8, 31))
    # August is EDT (UTC-4): midnight New York is 04:00 UTC.
    assert start == datetime(2026, 8, 1, 4, 0)
    assert end == datetime(2026, 9, 1, 4, 0)
    # Every instant inside the window maps back into the month.
    assert session_date(start) == date(2026, 8, 1)
    assert session_date(end - timedelta(seconds=1)) == date(2026, 8, 31)


def test_utc_window_spans_a_daylight_saving_transition() -> None:
    # DST starts 2026-03-08. The month opens at UTC-5 and closes at UTC-4.
    start, end = utc_window(date(2026, 3, 1), date(2026, 3, 31))
    assert start == datetime(2026, 3, 1, 5, 0)
    assert end == datetime(2026, 4, 1, 4, 0)


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def test_summarize_classifies_winners_losers_and_scratches() -> None:
    stats = summarize(
        [
            _execution(day=date(2026, 8, 19), pnl="120.50", reference_id=1),
            _execution(day=date(2026, 8, 19), pnl="-40.25", reference_id=2),
            _execution(day=date(2026, 8, 19), pnl="0", reference_id=3),
        ]
    )
    assert stats.realized_pnl == Decimal("80.25")
    assert stats.trade_count == 3
    assert stats.winning_trades == 1
    assert stats.losing_trades == 1
    # The scratch counts as a trade but decides nothing, so it is out of the
    # win-rate denominator.
    assert stats.win_rate == 0.5
    assert stats.gross_profit == Decimal("120.50")
    assert stats.gross_loss == Decimal("40.25")


def test_summarize_reports_no_win_rate_when_nothing_was_decided() -> None:
    stats = summarize([_execution(day=date(2026, 8, 19), pnl="0")])
    assert stats.trade_count == 1
    assert stats.win_rate is None


def test_profit_factor_is_none_when_nothing_was_lost() -> None:
    stats = summarize([_execution(day=date(2026, 8, 19), pnl="100")])
    assert stats.profit_factor is None


def test_profit_factor_divides_gross_profit_by_gross_loss() -> None:
    stats = summarize(
        [
            _execution(day=date(2026, 8, 19), pnl="300", reference_id=1),
            _execution(day=date(2026, 8, 19), pnl="-100", reference_id=2),
        ]
    )
    assert stats.profit_factor == 3.0


def test_summarize_keeps_decimal_precision() -> None:
    stats = summarize(
        [
            _execution(day=date(2026, 8, 19), pnl="0.10", reference_id=1),
            _execution(day=date(2026, 8, 19), pnl="0.20", reference_id=2),
        ]
    )
    # Exactly 0.30 — a float fold would give 0.30000000000000004.
    assert stats.realized_pnl == Decimal("0.30")


def test_empty_month_has_no_days_and_a_zero_total() -> None:
    month = build_month(year=2026, month=8, executions=[])
    assert month.days == []
    assert month.stats.realized_pnl == Decimal("0")
    assert month.stats.trade_count == 0
    # Weeks still cover the month so the calendar's summary column lines up.
    assert len(month.weeks) == len(week_spans(*month_bounds(2026, 8)))


def test_build_month_buckets_multiple_trades_and_symbols_per_day() -> None:
    month = build_month(
        year=2026,
        month=8,
        executions=[
            _execution(day=date(2026, 8, 19), pnl="100", ticker="AAPL", reference_id=1),
            _execution(day=date(2026, 8, 19), pnl="-30", ticker="MSFT", reference_id=2),
            _execution(day=date(2026, 8, 20), pnl="50", ticker="AAPL", reference_id=3),
        ],
    )
    by_date = {day.date: day for day in month.days}
    assert by_date[date(2026, 8, 19)].stats.realized_pnl == Decimal("70")
    assert by_date[date(2026, 8, 19)].stats.trade_count == 2
    assert by_date[date(2026, 8, 20)].stats.realized_pnl == Decimal("50")
    assert month.stats.realized_pnl == Decimal("120")


def test_build_month_drops_executions_outside_the_month() -> None:
    month = build_month(
        year=2026,
        month=8,
        executions=[
            _execution(day=date(2026, 7, 31), pnl="999", reference_id=1),
            _execution(day=date(2026, 8, 1), pnl="10", reference_id=2),
            _execution(day=date(2026, 9, 1), pnl="999", reference_id=3),
        ],
    )
    assert [day.date for day in month.days] == [date(2026, 8, 1)]
    assert month.stats.realized_pnl == Decimal("10")


def test_week_spans_are_monday_anchored_and_clipped_to_the_month() -> None:
    # 2026-08-01 is a Saturday; 2026-08-31 is a Monday.
    spans = week_spans(date(2026, 8, 1), date(2026, 8, 31))
    assert spans[0] == (date(2026, 8, 1), date(2026, 8, 2))
    assert spans[1] == (date(2026, 8, 3), date(2026, 8, 9))
    assert spans[-1] == (date(2026, 8, 31), date(2026, 8, 31))
    # Contiguous and complete.
    assert spans[0][0] == date(2026, 8, 1)
    assert spans[-1][1] == date(2026, 8, 31)
    for earlier, later in pairwise(spans):
        assert later[0] == earlier[1] + timedelta(days=1)


def test_weekly_aggregate_sums_only_its_own_days() -> None:
    month = build_month(
        year=2026,
        month=8,
        executions=[
            _execution(day=date(2026, 8, 3), pnl="100", reference_id=1),  # week 2
            _execution(day=date(2026, 8, 9), pnl="25", reference_id=2),  # week 2 (Sunday)
            _execution(day=date(2026, 8, 10), pnl="7", reference_id=3),  # week 3
        ],
    )
    by_start = {week.start: week for week in month.weeks}
    assert by_start[date(2026, 8, 3)].stats.realized_pnl == Decimal("125")
    assert by_start[date(2026, 8, 3)].stats.trade_count == 2
    assert by_start[date(2026, 8, 10)].stats.realized_pnl == Decimal("7")


def test_month_bounds_handles_december_rollover() -> None:
    assert month_bounds(2026, 12) == (date(2026, 12, 1), date(2026, 12, 31))
    assert month_bounds(2026, 2) == (date(2026, 2, 1), date(2026, 2, 28))
    assert month_bounds(2028, 2) == (date(2028, 2, 1), date(2028, 2, 29))


# ---------------------------------------------------------------------------
# Router — real ledger rows
# ---------------------------------------------------------------------------


def _add_trade(
    session: Session,
    *,
    portfolio_id: int,
    ts: datetime,
    realized: str | None,
    side: TradeSide = TradeSide.SELL,
    quantity: str = "10",
    price: str = "100",
    ticker: str = "AAPL",
) -> Trade:
    trade = Trade(
        portfolio_id=portfolio_id,
        ticker=ticker,
        side=side,
        quantity=Decimal(quantity),
        price=Decimal(price),
        ts=ts,
        fx_rate=Decimal(1),
        realized_pnl=None if realized is None else Decimal(realized),
    )
    session.add(trade)
    session.commit()
    session.refresh(trade)
    return trade


def test_month_endpoint_reports_only_realizing_executions(
    client: TestClient, session: Session
) -> None:
    _seed_symbol(session)
    user_id = _make_user(session, "month@stockviz.dev")
    portfolio = ensure_default_portfolio(session, user_id)
    assert portfolio.id is not None

    _add_trade(session, portfolio_id=portfolio.id, ts=datetime(2026, 8, 19, 18), realized="250.00")
    _add_trade(session, portfolio_id=portfolio.id, ts=datetime(2026, 8, 19, 19), realized="-50.00")
    # A buy realizes nothing and must not be counted as a trade.
    _add_trade(
        session,
        portfolio_id=portfolio.id,
        ts=datetime(2026, 8, 19, 17),
        realized=None,
        side=TradeSide.BUY,
    )

    res = client.get("/v1/portfolio/journal/months/2026/8", headers=_auth_headers(user_id))
    assert res.status_code == 200
    body = res.json()
    assert body["currency"] == "USD"
    assert body["summary"]["trade_count"] == 2
    assert Decimal(body["summary"]["realized_pnl"]) == Decimal("200.00")
    assert body["summary"]["winning_trades"] == 1
    assert body["summary"]["losing_trades"] == 1
    assert [day["date"] for day in body["days"]] == ["2026-08-19"]


def test_month_endpoint_attributes_a_late_utc_fill_to_the_previous_session(
    client: TestClient, session: Session
) -> None:
    _seed_symbol(session)
    user_id = _make_user(session, "tz@stockviz.dev")
    portfolio = ensure_default_portfolio(session, user_id)
    assert portfolio.id is not None
    # 2026-09-01T01:30Z is still 2026-08-31 in New York, so it belongs to
    # August — a naive UTC grouping would file it under September.
    _add_trade(session, portfolio_id=portfolio.id, ts=datetime(2026, 9, 1, 1, 30), realized="10.00")

    august = client.get(
        "/v1/portfolio/journal/months/2026/8", headers=_auth_headers(user_id)
    ).json()
    september = client.get(
        "/v1/portfolio/journal/months/2026/9", headers=_auth_headers(user_id)
    ).json()
    assert [day["date"] for day in august["days"]] == ["2026-08-31"]
    assert september["days"] == []


def test_month_endpoint_is_empty_for_an_account_with_no_closed_trades(
    client: TestClient, session: Session
) -> None:
    user_id = _make_user(session, "quiet@stockviz.dev")
    res = client.get("/v1/portfolio/journal/months/2026/8", headers=_auth_headers(user_id))
    assert res.status_code == 200
    body = res.json()
    assert body["days"] == []
    assert body["summary"]["trade_count"] == 0
    assert body["return_pct"] is None


def test_return_pct_uses_the_nav_snapshot_before_the_month(
    client: TestClient, session: Session
) -> None:
    _seed_symbol(session)
    user_id = _make_user(session, "return@stockviz.dev")
    portfolio = ensure_default_portfolio(session, user_id)
    assert portfolio.id is not None
    session.add(PortfolioSnapshot(user_id=user_id, date=date(2026, 7, 31), nav=Decimal("100000")))
    # A later snapshot inside the month must not become the denominator.
    session.add(PortfolioSnapshot(user_id=user_id, date=date(2026, 8, 15), nav=Decimal("50000")))
    session.commit()
    _add_trade(session, portfolio_id=portfolio.id, ts=datetime(2026, 8, 19, 18), realized="5000.00")

    body = client.get("/v1/portfolio/journal/months/2026/8", headers=_auth_headers(user_id)).json()
    assert Decimal(body["start_nav"]) == Decimal("100000")
    assert body["return_pct"] == 5.0


def test_legacy_day_detail_does_not_guess_cost_basis_from_rounded_pnl(
    client: TestClient, session: Session
) -> None:
    _seed_symbol(session)
    user_id = _make_user(session, "day@stockviz.dev")
    portfolio = ensure_default_portfolio(session, user_id)
    assert portfolio.id is not None
    # Sold 10 @ 229.12 for +27.20 => basis 226.40, exactly.
    _add_trade(
        session,
        portfolio_id=portfolio.id,
        ts=datetime(2026, 8, 19, 18),
        realized="27.20",
        quantity="10",
        price="229.12",
    )

    body = client.get(
        "/v1/portfolio/journal/days/2026-08-19", headers=_auth_headers(user_id)
    ).json()
    assert body["stats"]["trade_count"] == 1
    execution = body["executions"][0]
    assert execution["kind"] == "equity"
    assert execution["ticker"] == "AAPL"
    assert execution["avg_cost"] is None
    assert Decimal(execution["price"]) == Decimal("229.12")


def test_day_endpoint_includes_settled_option_realizations(
    client: TestClient, session: Session
) -> None:
    _seed_symbol(session)
    user_id = _make_user(session, "opt@stockviz.dev")
    portfolio = ensure_default_portfolio(session, user_id)
    assert portfolio.id is not None
    session.add(
        OptionsPosition(
            user_id=user_id,
            portfolio_id=portfolio.id,
            ticker="AAPL",
            option_type=OptionType.CALL,
            strike=Decimal("250"),
            expiry=date(2026, 9, 18),
            quantity=2,
            premium_paid=Decimal("400.00"),
            proceeds=Decimal("650.00"),
            realized_pnl=Decimal("250.00"),
            status=OptionStatus.CLOSED,
            settled_at=datetime(2026, 8, 19, 18),
        )
    )
    session.commit()

    body = client.get(
        "/v1/portfolio/journal/days/2026-08-19", headers=_auth_headers(user_id)
    ).json()
    execution = body["executions"][0]
    assert execution["kind"] == "option"
    assert execution["option_type"] == "call"
    assert execution["contracts"] == 2
    assert Decimal(execution["realized_pnl"]) == Decimal("250.00")
    assert Decimal(body["stats"]["realized_pnl"]) == Decimal("250.00")


def test_open_and_unrealized_options_are_excluded(client: TestClient, session: Session) -> None:
    _seed_symbol(session)
    user_id = _make_user(session, "openopt@stockviz.dev")
    portfolio = ensure_default_portfolio(session, user_id)
    assert portfolio.id is not None
    session.add_all(
        [
            # Still open — realizes nothing yet.
            OptionsPosition(
                user_id=user_id,
                portfolio_id=portfolio.id,
                ticker="AAPL",
                option_type=OptionType.PUT,
                strike=Decimal("200"),
                expiry=date(2026, 12, 18),
                quantity=1,
                premium_paid=Decimal("300.00"),
                status=OptionStatus.OPEN,
            ),
            # Settled before the realization columns existed: no persisted P&L,
            # so it is excluded rather than re-priced.
            OptionsPosition(
                user_id=user_id,
                portfolio_id=portfolio.id,
                ticker="AAPL",
                option_type=OptionType.CALL,
                strike=Decimal("200"),
                expiry=date(2026, 8, 21),
                quantity=1,
                premium_paid=Decimal("300.00"),
                status=OptionStatus.CLOSED,
                settled_at=datetime(2026, 8, 19, 18),
            ),
        ]
    )
    session.commit()

    body = client.get(
        "/v1/portfolio/journal/days/2026-08-19", headers=_auth_headers(user_id)
    ).json()
    assert body["executions"] == []
    assert body["stats"]["trade_count"] == 0
    assert body["unavailable_count"] == 1
    week = client.get(
        "/v1/portfolio/journal/weeks/2026-08-17", headers=_auth_headers(user_id)
    ).json()
    assert week["unavailable_count"] == 1
    month = client.get("/v1/portfolio/journal/months/2026/8", headers=_auth_headers(user_id)).json()
    assert month["unavailable_count"] == 1


def test_closing_time_recommendation_is_not_misrepresented_as_entry_signal(
    client: TestClient, session: Session
) -> None:
    _seed_symbol(session)
    user_id = _make_user(session, "signal@stockviz.dev")
    portfolio = ensure_default_portfolio(session, user_id)
    assert portfolio.id is not None
    session.add_all(
        [
            Recommendation(
                ticker="AAPL", score=Decimal(5), computed_at=datetime(2026, 8, 18, 21, 0)
            ),
            # Computed after the fill — must never be attached.
            Recommendation(
                ticker="AAPL", score=Decimal(7), computed_at=datetime(2026, 8, 19, 23, 0)
            ),
        ]
    )
    session.commit()
    _add_trade(session, portfolio_id=portfolio.id, ts=datetime(2026, 8, 19, 18), realized="12.00")

    body = client.get(
        "/v1/portfolio/journal/days/2026-08-19", headers=_auth_headers(user_id)
    ).json()
    # A closing fill does not identify the opening lots in this average-cost
    # book. A score before the SELL is not evidence of the signal at entry.
    assert body["executions"][0]["signal_at_entry"] is None


def test_execution_timestamp_has_an_explicit_utc_offset(
    client: TestClient, session: Session
) -> None:
    _seed_symbol(session)
    user = _make_user(session, "utc-output@stockviz.dev")
    portfolio = ensure_default_portfolio(session, user)
    assert portfolio.id is not None
    _add_trade(session, portfolio_id=portfolio.id, ts=datetime(2026, 8, 19, 18), realized="10")
    body = client.get("/v1/portfolio/journal/days/2026-08-19", headers=_auth_headers(user)).json()
    assert datetime.fromisoformat(body["executions"][0]["executed_at"]).utcoffset() == timedelta(0)


def test_scale_in_and_partial_closes_reconcile_with_the_fill_ledger(
    client: TestClient,
    session: Session,
) -> None:
    from stockviz.services.trading.execute import apply_fill

    _seed_symbol(session)
    user = _make_user(session, "partial-journal@stockviz.dev")
    portfolio = ensure_default_portfolio(session, user)
    for side, quantity, price in [
        (TradeSide.BUY, "10", "100"),
        (TradeSide.BUY, "10", "120"),
        (TradeSide.SELL, "5", "130"),
        (TradeSide.SELL, "15", "100"),
    ]:
        fill = apply_fill(
            session,
            portfolio=portfolio,
            ticker="AAPL",
            side=side,
            quantity=Decimal(quantity),
            price=Decimal(price),
            currency="USD",
            fx_rate=Decimal(1),
        )
        fill.trade.ts = datetime(2026, 8, 19, 18)
        session.add(fill.trade)
        session.commit()
    body = client.get("/v1/portfolio/journal/days/2026-08-19", headers=_auth_headers(user)).json()
    assert body["stats"]["trade_count"] == 2
    assert Decimal(body["stats"]["realized_pnl"]) == Decimal("-50")
    assert [Decimal(row["avg_cost"]) for row in body["executions"]] == [Decimal("110")] * 2


def test_no_signal_is_shown_when_none_was_computed_before_the_fill(
    client: TestClient, session: Session
) -> None:
    _seed_symbol(session)
    user_id = _make_user(session, "nosignal@stockviz.dev")
    portfolio = ensure_default_portfolio(session, user_id)
    assert portfolio.id is not None
    session.add(
        Recommendation(ticker="AAPL", score=Decimal(6), computed_at=datetime(2026, 8, 20, 21, 0))
    )
    session.commit()
    _add_trade(session, portfolio_id=portfolio.id, ts=datetime(2026, 8, 19, 18), realized="12.00")

    body = client.get(
        "/v1/portfolio/journal/days/2026-08-19", headers=_auth_headers(user_id)
    ).json()
    assert body["executions"][0]["signal_at_entry"] is None


# ---------------------------------------------------------------------------
# Isolation and validation
# ---------------------------------------------------------------------------


def test_one_user_never_sees_another_users_journal(client: TestClient, session: Session) -> None:
    _seed_symbol(session)
    owner = _make_user(session, "owner@stockviz.dev")
    intruder = _make_user(session, "intruder@stockviz.dev")
    owner_portfolio = ensure_default_portfolio(session, owner)
    assert owner_portfolio.id is not None
    _add_trade(
        session, portfolio_id=owner_portfolio.id, ts=datetime(2026, 8, 19, 18), realized="900.00"
    )

    owner_body = client.get(
        "/v1/portfolio/journal/months/2026/8", headers=_auth_headers(owner)
    ).json()
    intruder_body = client.get(
        "/v1/portfolio/journal/months/2026/8", headers=_auth_headers(intruder)
    ).json()
    assert Decimal(owner_body["summary"]["realized_pnl"]) == Decimal("900.00")
    assert intruder_body["days"] == []
    assert intruder_body["summary"]["trade_count"] == 0

    owner_day = client.get(
        "/v1/portfolio/journal/days/2026-08-19", headers=_auth_headers(owner)
    ).json()
    intruder_day = client.get(
        "/v1/portfolio/journal/days/2026-08-19", headers=_auth_headers(intruder)
    ).json()
    assert len(owner_day["executions"]) == 1
    assert intruder_day["executions"] == []


def test_journal_requires_authentication(client: TestClient) -> None:
    assert client.get("/v1/portfolio/journal/months/2026/8").status_code == 401
    assert client.get("/v1/portfolio/journal/days/2026-08-19").status_code == 401


def test_month_endpoint_rejects_an_impossible_month(client: TestClient, session: Session) -> None:
    user_id = _make_user(session, "bad@stockviz.dev")
    res = client.get("/v1/portfolio/journal/months/2026/13", headers=_auth_headers(user_id))
    assert res.status_code == 422


def test_day_pagination_keeps_full_day_totals_and_stable_tied_fills(
    client: TestClient, session: Session
) -> None:
    _seed_symbol(session)
    user = _make_user(session, "pages@stockviz.dev")
    portfolio = ensure_default_portfolio(session, user)
    assert portfolio.id is not None
    trades = [
        _add_trade(
            session, portfolio_id=portfolio.id, ts=datetime(2026, 8, 19, 18), realized=str(value)
        )
        for value in (10, -3, 0)
    ]
    url = "/v1/portfolio/journal/days/2026-08-19"
    first = client.get(f"{url}?limit=2", headers=_auth_headers(user)).json()
    second = client.get(f"{url}?limit=2&offset=2", headers=_auth_headers(user)).json()
    assert first["stats"]["trade_count"] == second["stats"]["trade_count"] == 3
    assert first["has_more"] is True and second["has_more"] is False
    assert [row["reference_id"] for row in first["executions"] + second["executions"]] == [
        trade.id for trade in trades
    ]
    assert client.get(f"{url}?limit=10000", headers=_auth_headers(user)).status_code == 422


def test_week_detail_extremes_and_ownership(client: TestClient, session: Session) -> None:
    _seed_symbol(session)
    user = _make_user(session, "week@stockviz.dev")
    other = _make_user(session, "week-other@stockviz.dev")
    portfolio = ensure_default_portfolio(session, user)
    assert portfolio.id is not None
    for day, pnl in [(19, "10"), (20, "-3"), (24, "999")]:
        _add_trade(session, portfolio_id=portfolio.id, ts=datetime(2026, 8, day, 18), realized=pnl)
    url = "/v1/portfolio/journal/weeks/2026-08-17"
    response = client.get(url, headers=_auth_headers(user))
    assert response.status_code == 200
    body = response.json()
    assert Decimal(body["stats"]["realized_pnl"]) == Decimal("7")
    assert Decimal(body["best_trade"]["realized_pnl"]) == Decimal("10")
    assert Decimal(body["worst_trade"]["realized_pnl"]) == Decimal("-3")
    assert body["end"] == "2026-08-23"
    assert client.get(url, headers=_auth_headers(other)).json()["best_trade"] is None
    assert client.get(url).status_code == 401
    assert (
        client.get(
            "/v1/portfolio/journal/weeks/2026-08-18", headers=_auth_headers(user)
        ).status_code
        == 422
    )


def test_active_account_keeps_month_payload_and_day_pages_bounded(
    client: TestClient, session: Session
) -> None:
    _seed_symbol(session)
    user = _make_user(session, "volume@stockviz.dev")
    portfolio = ensure_default_portfolio(session, user)
    assert portfolio.id is not None
    session.add_all(
        [
            Trade(
                portfolio_id=portfolio.id,
                ticker="AAPL",
                side=TradeSide.SELL,
                quantity=Decimal(1),
                price=Decimal(100),
                realized_pnl=Decimal("0.01"),
                ts=datetime(2026, 8, 19, 18),
            )
            for _ in range(1000)
        ]
    )
    session.commit()
    month = client.get("/v1/portfolio/journal/months/2026/8", headers=_auth_headers(user))
    assert len(month.content) < 10000
    assert Decimal(month.json()["summary"]["realized_pnl"]) == Decimal("10")
    day = client.get("/v1/portfolio/journal/days/2026-08-19", headers=_auth_headers(user)).json()
    assert day["stats"]["trade_count"] == 1000
    assert len(day["executions"]) == 100
    assert day["has_more"] is True
