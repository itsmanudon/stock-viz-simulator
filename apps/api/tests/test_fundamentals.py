"""Phase 6.3: fundamentals stored point-in-time, from yfinance and EDGAR.

No provider is called. yfinance statements are fake frames in yfinance's
shape (rows = line items, columns = period ends); the EDGAR payload follows
the documented companyfacts layout (facts -> namespace -> tag -> units).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pandas as pd
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from stockviz.models import FundamentalFact
from stockviz.services.fundamentals import edgar_source, yfinance_source
from stockviz.services.fundamentals.ingest import ingest
from stockviz.services.fundamentals.store import FactRecord, facts_as_of, record_facts
from stockviz.services.instruments import instrument_ids
from tests.symbols import seed_symbols

FY24, FY25 = pd.Timestamp("2024-09-30"), pd.Timestamp("2025-09-30")


class FakeTicker:
    def __init__(self, revenue_25: float = 400.0) -> None:
        self.info = {"financialCurrency": "USD"}
        self.income_stmt = pd.DataFrame(
            {FY25: [revenue_25, 100.0, 6.5], FY24: [380.0, 95.0, 6.0]},
            index=["Total Revenue", "Net Income", "Diluted EPS"],
        )
        self.cashflow = pd.DataFrame(
            {FY25: [-12.0, 120.0], FY24: [-11.0, float("nan")]},
            index=["Capital Expenditure", "Operating Cash Flow"],
        )
        self.balance_sheet = pd.DataFrame(
            {FY25: [360.0, 15.0], FY24: [350.0, 15.2]},
            index=["Total Assets", "Ordinary Shares Number"],
        )
        self.quarterly_income_stmt = pd.DataFrame()
        self.quarterly_cashflow = None
        self.quarterly_balance_sheet = pd.DataFrame()


def _iid(session: Session, ticker: str = "AAPL") -> int:
    seed_symbols(session, ticker)
    return instrument_ids(session, [ticker])[ticker]


def _yf(day: date, revenue_25: float = 400.0) -> list[FactRecord]:
    return yfinance_source.fetch_facts(
        "AAPL", today=day, ticker_factory=lambda _s: FakeTicker(revenue_25)
    )


def test_yfinance_statements_become_labelled_facts() -> None:
    facts = {(f.concept, f.period_type, f.period_end): f for f in _yf(date(2026, 11, 12))}
    revenue = facts[("revenue", "annual", date(2025, 9, 30))]
    assert (revenue.value, revenue.unit, revenue.point_in_time) == (Decimal("400.0"), "USD", False)
    assert facts[("eps_diluted", "annual", date(2025, 9, 30))].unit == "USD/share"
    assert facts[("capex", "annual", date(2025, 9, 30))].value == Decimal(
        "12.0"
    )  # outflow positive
    assert facts[("total_assets", "instant", date(2024, 9, 30))].value == Decimal("350.0")
    assert facts[("shares_outstanding", "instant", date(2025, 9, 30))].unit == "shares"
    assert ("operating_cash_flow", "annual", date(2024, 9, 30)) not in facts  # NaN skipped


def test_rerun_writes_nothing_and_a_change_is_a_new_version(session: Session) -> None:
    iid = _iid(session)
    first = record_facts(session, iid, _yf(date(2026, 11, 1)))
    session.commit()
    assert first > 0
    assert record_facts(session, iid, _yf(date(2026, 11, 8))) == 0
    assert record_facts(session, iid, _yf(date(2026, 11, 15), revenue_25=410.0)) == 1
    session.commit()

    def revenue_on(day: date) -> Decimal:
        return facts_as_of(session, iid, day)[("revenue", "annual", date(2025, 9, 30))].value

    assert revenue_on(date(2026, 11, 10)) == Decimal("400.0")
    assert revenue_on(date(2026, 11, 20)) == Decimal("410.0")
    assert facts_as_of(session, iid, date(2026, 10, 1)) == {}  # nothing known yet


def _edgar_payload() -> dict:
    def entry(start, end, val, form, filed, fp, fy=2025, accn="0000320193-25-000001"):
        e = {"end": end, "val": val, "form": form, "filed": filed, "fp": fp, "fy": fy, "accn": accn}
        if start:
            e["start"] = start
        return e

    return {
        "cik": 320193,
        "entityName": "Apple Inc.",
        "facts": {
            "us-gaap": {
                "RevenueFromContractWithCustomerExcludingAssessedTax": {
                    "units": {
                        "USD": [
                            entry("2025-03-30", "2025-06-28", 94.0, "10-Q", "2025-08-01", "Q3"),
                            entry("2024-09-29", "2025-06-28", 313.0, "10-Q", "2025-08-01", "Q3"),
                            entry("2024-09-29", "2025-09-27", 416.0, "10-K", "2025-10-31", "FY"),
                            # the next 10-K repeats it unchanged, then a restatement
                            entry("2024-09-29", "2025-09-27", 416.0, "10-K", "2026-10-30", "FY"),
                            entry("2024-09-29", "2025-09-27", 415.0, "10-K/A", "2026-12-01", "FY"),
                            entry("2025-03-30", "2025-06-28", 1.0, "8-K", "2025-07-15", "Q3"),
                        ]
                    }
                },
                "Assets": {
                    "units": {"USD": [entry(None, "2025-09-27", 360.0, "10-K", "2025-10-31", "FY")]}
                },
                "EarningsPerShareDiluted": {
                    "units": {
                        "USD/shares": [
                            entry("2024-09-29", "2025-09-27", 7.46, "10-K", "2025-10-31", "FY")
                        ]
                    }
                },
            },
            "dei": {
                "EntityCommonStockSharesOutstanding": {
                    "units": {
                        "shares": [entry(None, "2025-10-17", 14.8, "10-K", "2025-10-31", "FY")]
                    }
                }
            },
        },
    }


def test_edgar_facts_are_point_in_time_and_skip_ytd() -> None:
    facts = edgar_source.parse_facts(_edgar_payload())
    kinds = {(f.concept, f.period_type, f.value, f.available_at) for f in facts}
    assert ("revenue", "quarter", Decimal("94.0"), date(2025, 8, 1)) in kinds
    assert not any(f.value == Decimal("313.0") for f in facts)  # nine-month YTD
    assert not any(f.value == Decimal("1.0") for f in facts)  # an 8-K
    eps = next(f for f in facts if f.concept == "eps_diluted")
    assert eps.unit == "USD/share" and eps.point_in_time
    shares = next(f for f in facts if f.concept == "shares_outstanding")
    assert (shares.period_type, shares.unit) == ("instant", "shares")


def test_edgar_restatement_is_a_new_version_and_as_of_sees_the_old(session: Session) -> None:
    iid = _iid(session)
    record_facts(session, iid, edgar_source.parse_facts(_edgar_payload()))
    session.commit()
    rows = session.exec(
        select(FundamentalFact).where(
            FundamentalFact.concept == "revenue", FundamentalFact.period_type == "annual"
        )
    ).all()
    assert sorted((r.value, r.available_at) for r in rows) == [
        (Decimal("415.0"), date(2026, 12, 1)),
        (Decimal("416.0"), date(2025, 10, 31)),  # the unchanged repeat wrote nothing
    ]
    key = ("revenue", "annual", date(2025, 9, 27))
    assert facts_as_of(session, iid, date(2026, 1, 1))[key].value == Decimal("416.0")
    assert facts_as_of(session, iid, date(2026, 12, 2))[key].value == Decimal("415.0")


def test_endpoint_table_as_of_and_source_preference(session: Session, client: TestClient) -> None:
    iid = _iid(session)
    record_facts(session, iid, _yf(date(2026, 11, 1)))
    # EDGAR has the same FY2025 revenue period under its own end date; give
    # yfinance a matching one to check EDGAR wins when both cover a period.
    record_facts(
        session,
        iid,
        [
            FactRecord(
                concept="revenue",
                period_type="annual",
                period_end=date(2025, 9, 30),
                value=Decimal("401"),
                unit="USD",
                currency="USD",
                available_at=date(2025, 11, 1),
                point_in_time=True,
                source="edgar",
                source_concept="us-gaap:Revenues",
            )
        ],
    )
    session.commit()

    body = client.get("/v1/symbols/AAPL/fundamentals", params={"period": "annual"}).json()
    assert body["periods"] == ["2025-09-30", "2024-09-30"]
    revenue = next(r for r in body["rows"] if r["concept"] == "revenue")
    assert Decimal(revenue["values"][0]) == Decimal("401")  # EDGAR over yfinance
    assert body["point_in_time"] is False  # other rows are yfinance
    assert set(body["sources"]) == {"edgar", "yfinance"}

    past = client.get(
        "/v1/symbols/AAPL/fundamentals", params={"period": "annual", "as_of": "2025-12-01"}
    ).json()
    assert [r["concept"] for r in past["rows"]] == ["revenue"]  # yfinance not fetched yet
    assert past["point_in_time"] is True


def test_ingest_reports_a_failure_and_keeps_going(session: Session) -> None:
    _iid(session, "AAPL")
    _iid(session, "MSFT")

    def fetch(ticker: str) -> list[FactRecord]:
        if ticker == "MSFT":
            raise RuntimeError("provider said no")
        return _yf(date(2026, 11, 1))

    report = ingest(session, ["MSFT", "AAPL"], fetch)
    assert report.failed == {"MSFT": "provider said no"} and report.written["AAPL"] > 0


def test_edgar_is_off_without_a_contact(monkeypatch, capsys) -> None:
    from stockviz import cli

    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    cli.get_settings.cache_clear()
    assert cli.main(["fundamentals", "--source", "edgar", "AAPL"]) == 2
    assert "EDGAR is off" in capsys.readouterr().out
