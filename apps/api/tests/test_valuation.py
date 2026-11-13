"""Phase 6.4: valuation as of a date, worked by hand.

INFY.NS trades in INR and reports in USD. On 10 Nov 2026 it closes at
Rs 1,500 and 1 INR = 0.012 USD, so the price in its reporting currency is
$18.00. With 4,000 shares the market cap is $72,000.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from stockviz.models import FxRate, PriceBar
from stockviz.services.fundamentals.store import FactRecord, record_facts
from stockviz.services.fundamentals.valuation import history, ttm, valuation
from stockviz.services.instruments import instrument_ids
from tests.symbols import seed_symbols

QUARTERS = [date(2025, 12, 31), date(2026, 3, 31), date(2026, 6, 30), date(2026, 9, 30)]
KNOWN = date(2026, 10, 20)


def _fact(concept, ptype, end, value, *, unit="USD", known=KNOWN) -> FactRecord:
    return FactRecord(
        concept=concept,
        period_type=ptype,
        period_end=end,
        value=Decimal(str(value)),
        unit=unit,
        currency=None if unit == "shares" else "USD",
        available_at=known,
        point_in_time=True,
        source="edgar",
        source_concept=f"test:{concept}",
    )


def _bar(day: date, close: str) -> PriceBar:
    c = Decimal(close)
    return PriceBar(
        ticker="INFY.NS",
        ts=datetime.combine(day, datetime.min.time()),
        interval="1d",
        open=c,
        high=c,
        low=c,
        close=c,
        volume=1,
        source="test",
    )


def _seed(session: Session, *, net_income_q: float = 1000) -> int:
    seed_symbols(session, "INFY.NS", currency="INR")
    iid = instrument_ids(session, ["INFY.NS"])["INFY.NS"]
    records = []
    for end in QUARTERS:
        records += [
            _fact("revenue", "quarter", end, 5000),
            _fact("net_income", "quarter", end, net_income_q),
            _fact("ebitda", "quarter", end, 1500),
            _fact("gross_profit", "quarter", end, 2000),
        ]
    records += [
        _fact("equity", "instant", QUARTERS[-1], 36000),
        _fact("cash", "instant", QUARTERS[-1], 2000),
        _fact("total_debt", "instant", QUARTERS[-1], 10000),
        _fact("shares_outstanding", "instant", QUARTERS[-1], 4000, unit="shares"),
        # A year earlier, revenue was 16,000 (annual), known well before.
        _fact("revenue", "annual", date(2025, 3, 31), 16000, known=date(2025, 5, 1)),
    ]
    record_facts(session, iid, records)
    session.add(_bar(date(2026, 11, 10), "1500"))
    session.add(_bar(date(2026, 10, 30), "1250"))
    session.add(FxRate(currency="INR", date=date(2026, 10, 1), usd_rate=Decimal("0.012")))
    session.commit()
    return iid


def test_multiples_worked_by_hand(session: Session) -> None:
    _seed(session)
    v = valuation(session, "INFY.NS", date(2026, 11, 10))
    assert (v.trading_currency, v.reporting_currency, v.basis) == ("INR", "USD", "ttm")
    assert v.fx_rate == Decimal("0.012")
    assert v.value("market_cap") == pytest.approx(72_000)
    assert v.value("pe") == pytest.approx(18.0)  # 72,000 / 4 x 1,000
    assert v.value("ps") == pytest.approx(3.6)  # 72,000 / 20,000
    assert v.value("pb") == pytest.approx(2.0)  # 72,000 / 36,000
    assert v.value("enterprise_value") == pytest.approx(80_000)  # + 10,000 debt - 2,000 cash
    assert v.value("ev_ebitda") == pytest.approx(80_000 / 6_000)
    assert v.value("gross_margin") == pytest.approx(40.0)
    assert v.value("net_margin") == pytest.approx(20.0)
    assert v.value("debt_to_equity") == pytest.approx(10_000 / 36_000)
    assert v.value("revenue_growth") == pytest.approx(25.0)  # 20,000 vs 16,000
    yield_metric = next(m for m in v.metrics if m.key == "dividend_yield")
    assert yield_metric.value is None and yield_metric.reason == "no dividends reported"
    assert v.point_in_time and v.sources == ["edgar"]


def test_a_loss_has_no_pe_and_says_so(session: Session) -> None:
    _seed(session, net_income_q=-100)
    v = valuation(session, "INFY.NS", date(2026, 11, 10))
    pe = next(m for m in v.metrics if m.key == "pe")
    assert pe.value is None and pe.reason == "loss"


def test_before_the_filing_nothing_is_known(session: Session) -> None:
    _seed(session)
    v = valuation(session, "INFY.NS", date(2026, 10, 15))  # quarters known 20 Oct
    # Only the 2025 annual revenue (filed May 2025) is known: no P/E yet.
    assert v.value("pe") is None and v.basis == "annual"
    reasons = {m.key: m.reason for m in v.metrics}
    assert reasons["market_cap"] == "no close or FX rate"


def test_ttm_falls_back_to_the_year_when_quarters_have_gaps() -> None:
    from stockviz.models.fundamentals import FundamentalFact

    def row(end: date, ptype: str, value: int) -> FundamentalFact:
        return FundamentalFact(
            instrument_id=1, concept="revenue", period_type=ptype, period_end=end,
            value=Decimal(value), unit="USD", available_at=KNOWN, point_in_time=True,
            source="edgar", source_concept="t",
        )  # fmt: skip

    gappy = [date(2026, 9, 30), date(2026, 6, 30), date(2025, 12, 31), date(2025, 9, 30)]
    known = {("revenue", "quarter", e): row(e, "quarter", 10) for e in gappy}
    known[("revenue", "annual", date(2026, 3, 31))] = row(date(2026, 3, 31), "annual", 99)
    value, basis, _used = ttm(known, "revenue")
    assert (value, basis) == (Decimal(99), "annual")


def test_history_and_percentile(session: Session, client: TestClient) -> None:
    _seed(session)
    points, pct = history(session, "INFY.NS", "pe", end=date(2026, 11, 10), years=1)
    # October's month-end uses the 30 Oct close (1,250 -> P/E 15); November's
    # point is 10 Nov (P/E 18). Months before the filing have no P/E.
    assert [round(v, 6) for _d, v in points] == [15.0, 18.0]
    assert pct == pytest.approx(100.0)

    body = client.get("/v1/symbols/INFY.NS/valuation", params={"as_of": "2026-11-10"}).json()
    assert body["reporting_currency"] == "USD" and body["trading_currency"] == "INR"
    pe = next(m for m in body["metrics"] if m["key"] == "pe")
    assert pe["value"] == pytest.approx(18.0)
    assert client.get("/v1/symbols/INFY.NS/valuation/history?metric=nope").status_code == 422
