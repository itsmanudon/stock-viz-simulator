"""A9.6 (M10.8): the 12-month dividend projection, by hand."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from stockviz.models import PriceBar
from stockviz.services import dividend_projection as dp
from tests.test_dividends import (
    _add_dividend,
    _add_position,
    _auth_headers,
    _make_portfolio,
    _seed_symbol,
)

ON = date(2026, 11, 20)


def _quarterly(first_year: int, per_year: list[Decimal]) -> list[tuple[date, Decimal]]:
    out = []
    for i, total in enumerate(per_year):
        for month in (2, 5, 8, 11):
            out.append((date(first_year + i, month, 10), total / 4))
    return out


def test_ttm_growth_and_projection_by_hand() -> None:
    # 1.00, 1.10, 1.21, 1.331 a year: 10% growth, quarterly.
    totals = [Decimal("1.00"), Decimal("1.10"), Decimal("1.21"), Decimal("1.331")]
    hist = _quarterly(2023, totals)
    out = dp.project("ACME", "USD", Decimal(10), hist, Decimal("50"), ON)
    # TTM on 20 Nov 2026: Feb, May, Aug, Nov 2026 = 1.331.
    assert out.ttm_per_share == Decimal("1.331")
    # Three years earlier the TTM was 2023's 1.00: growth (1.331)^(1/3) - 1 = 10%.
    assert out.growth_3y == pytest.approx(0.10, abs=1e-9)
    assert out.next_12m_per_share == Decimal("1.4641")
    assert out.next_12m_total == Decimal("14.64")
    assert out.forward_yield == pytest.approx(1.4641 / 50, abs=1e-6)
    assert [p["ex_date"] for p in out.payouts] == [date(2027, m, 10) for m in (2, 5, 8, 11)]
    assert out.streak_years == 2  # 2025 > 2024 > 2023; 2026 is not complete


def test_growth_is_capped_and_missing_history_uses_zero() -> None:
    jump = _quarterly(2023, [Decimal("0.10"), Decimal("1"), Decimal("1"), Decimal("1")])
    out = dp.project("ACME", "USD", Decimal(1), jump, None, ON)
    assert out.growth_3y is not None and out.growth_3y > 0.25
    assert out.growth_used == 0.25 and out.forward_yield is None
    short = _quarterly(2026, [Decimal("2")])
    out = dp.project("ACME", "USD", Decimal(1), short, None, ON)
    assert out.growth_3y is None and out.growth_used == 0.0
    assert out.next_12m_per_share == Decimal("2.0000")


def test_no_recent_dividend_has_a_reason() -> None:
    old = [(ON - timedelta(days=800), Decimal("1"))]
    out = dp.project("ACME", "USD", Decimal(5), old, None, ON)
    assert out.reason and out.next_12m_total == 0 and not out.payouts


def test_route_adds_the_projection(session: Session, client: TestClient) -> None:
    _seed_symbol(session, "AAPL")
    user_id, portfolio_id = _make_portfolio(session, email="proj@stockviz.dev")
    _add_position(session, portfolio_id, "AAPL", Decimal("10"))
    today = datetime.utcnow().date()
    for back in (30, 120, 210, 300):
        _add_dividend(session, "AAPL", today - timedelta(days=back), Decimal("0.25"))
    session.add(PriceBar(ticker="AAPL", ts=datetime.combine(today, datetime.min.time()),
                         interval="1d", open=Decimal(100), high=Decimal(100), low=Decimal(100),
                         close=Decimal(100), volume=1, source="test"))  # fmt: skip
    session.commit()
    body = client.get("/v1/portfolio/dividends", headers=_auth_headers(user_id)).json()
    (h,) = body["projection"]
    assert Decimal(h["ttm_per_share"]) == Decimal("1.00")
    assert Decimal(h["next_12m_total"]) == Decimal("10.00")
    assert h["forward_yield"] == pytest.approx(0.01)
    assert len(h["payouts"]) == 4
    assert Decimal(body["projection_totals"]["USD"]) == Decimal("10.00")
    assert "projection, not a declaration" in body["projection_method"]
