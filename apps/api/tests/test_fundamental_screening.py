"""Phase 6.5: screening both markets on fundamentals (the phase's acceptance, API side).

AAPL (USD) and INFY.NS (INR listing, USD reports) get stored financials, then
the nightly metrics refresh writes their valuation into the snapshot.
INFY.NS: Rs 1,500 x 0.012 = $18.00 x 4,000 shares = $72,000 market cap,
P/E 18. AAPL: $100 x 1,000 shares = $100,000, net income 4 x 500 -> P/E 50.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from stockviz.models import FxRate, PriceBar
from stockviz.services.fundamentals.store import FactRecord, record_facts
from stockviz.services.instruments import instrument_ids
from stockviz.services.metrics import refresh_symbol_metrics
from tests.symbols import seed_symbols

QUARTERS = [date(2025, 12, 31), date(2026, 3, 31), date(2026, 6, 30), date(2026, 9, 30)]


def _fact(concept, ptype, end, value, unit="USD") -> FactRecord:
    return FactRecord(
        concept=concept, period_type=ptype, period_end=end, value=Decimal(str(value)),
        unit=unit, currency=None if unit == "shares" else "USD", available_at=date(2026, 10, 20),
        point_in_time=True, source="edgar", source_concept=f"t:{concept}",
    )  # fmt: skip


def _company(session, ticker, currency, close, shares, ni_q, equity) -> None:
    seed_symbols(session, ticker, currency=currency)
    iid = instrument_ids(session, [ticker])[ticker]
    recs = [_fact("net_income", "quarter", q, ni_q) for q in QUARTERS]
    recs += [_fact("revenue", "quarter", q, ni_q * 5) for q in QUARTERS]
    recs += [
        _fact("equity", "instant", QUARTERS[-1], equity),
        _fact("shares_outstanding", "instant", QUARTERS[-1], shares, unit="shares"),
    ]
    record_facts(session, iid, recs)
    for i in range(30):
        c = Decimal(str(close))
        session.add(
            PriceBar(
                ticker=ticker, ts=datetime(2026, 10, 12) + timedelta(days=i), interval="1d",
                open=c, high=c, low=c, close=c, volume=1, source="test",
            )
        )  # fmt: skip


def _seed(session: Session) -> None:
    _company(session, "AAPL", "USD", 100, 1000, 500, 50_000)
    _company(session, "INFY.NS", "INR", 1500, 4000, 1000, 36_000)
    session.add(FxRate(currency="INR", date=date(2026, 10, 1), usd_rate=Decimal("0.012")))
    session.commit()
    refresh_symbol_metrics(session)
    session.commit()


def test_snapshot_holds_valuation_in_comparable_units(session: Session, client: TestClient) -> None:
    _seed(session)
    rows = {r["ticker"]: r for r in client.get("/v1/screener").json()["rows"]}
    assert rows["INFY.NS"]["pe"] == pytest.approx(18.0)
    assert rows["INFY.NS"]["market_cap_usd"] == pytest.approx(72_000)  # reported in USD already
    assert rows["AAPL"]["pe"] == pytest.approx(50.0)
    assert rows["AAPL"]["pb"] == pytest.approx(2.0)


def test_fundamental_filters_and_sort_across_markets(session: Session, client: TestClient) -> None:
    _seed(session)
    cheap = client.get("/v1/screener", params={"pe_max": 20}).json()
    assert [r["ticker"] for r in cheap["rows"]] == ["INFY.NS"]
    both = client.get(
        "/v1/screener",
        params={"market": "US,IN", "sort": "market_cap_usd", "dir": "desc", "pe_min": 1},
    ).json()
    assert [r["ticker"] for r in both["rows"]] == ["AAPL", "INFY.NS"]
    big = client.get("/v1/screener", params={"market_cap_usd_min": 80_000}).json()
    assert [r["ticker"] for r in big["rows"]] == ["AAPL"]
