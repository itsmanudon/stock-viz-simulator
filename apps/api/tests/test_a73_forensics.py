"""A7.3 (M5.1, M5.2): the forensic scorecard, worked by hand."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from stockviz.models import Symbol
from stockviz.services.fundamentals import forensics as fx
from stockviz.services.fundamentals.concepts import CONCEPTS
from stockviz.services.fundamentals.store import FactRecord, record_facts
from stockviz.services.instruments import instrument_ids

D = Decimal


def _year(**values: float) -> dict[str, Decimal | None]:
    return {k: D(str(v)) for k, v in values.items()}


# Three years of a healthy, improving company.
T2 = _year(total_assets=900, net_income=40, revenue=800)
T1 = _year(total_assets=1000, net_income=50, revenue=900, operating_cash_flow=60,
           long_term_debt=300, current_assets=400, current_liabilities=250,
           shares_outstanding=100, gross_profit=360, receivables=90, net_ppe=300,
           depreciation=30, sga=100)  # fmt: skip
T = _year(total_assets=1100, net_income=80, revenue=1000, operating_cash_flow=100,
          long_term_debt=280, current_assets=480, current_liabilities=260,
          shares_outstanding=100, gross_profit=420, receivables=95, net_ppe=320,
          depreciation=34, sga=105, retained_earnings=300, operating_income=110,
          equity=560, total_liabilities=540)  # fmt: skip


def test_piotroski_by_hand() -> None:
    p = fx.piotroski(T, T1, T2)
    results = {t.key: t.result for t in p.tests}
    # ROA 80/1000 = 0.08 > 0; CFO 100 > 0; ROA up from 50/900; 100 > 80;
    # leverage 280/1050 < 300/950; current ratio 1.846 > 1.6; shares equal;
    # gross margin 0.42 > 0.40; turnover 1000/1000 > 900/900? equal -> fail.
    assert results == {"roa": "pass", "cfo": "pass", "delta_roa": "pass", "accrual": "pass",
                       "delta_leverage": "pass", "delta_liquidity": "pass",
                       "no_dilution": "pass", "delta_margin": "pass",
                       "delta_turnover": "fail"}  # fmt: skip
    assert (p.score, p.known) == (8, 9)


def test_piotroski_counts_unknowns_and_names_the_debt_stand_in() -> None:
    t = {k: v for k, v in T.items() if k not in ("gross_profit", "long_term_debt")}
    t["total_debt"] = D(300)
    t1 = {**T1, "total_debt": D(320)}
    p = fx.piotroski(t, t1, None)
    results = {x.key: x for x in p.tests}
    assert results["delta_margin"].result == "unknown"
    assert results["delta_roa"].result == "unknown"  # no assets two years back
    assert results["delta_turnover"].result == "unknown"  # needs year t-2's assets too
    assert "total debt" in results["delta_leverage"].detail
    assert p.known == 6


def test_altman_z_em_by_hand() -> None:
    z = fx.altman_z_em(T)
    x1, x2, x3, x4 = (480 - 260) / 1100, 300 / 1100, 110 / 1100, 560 / 540
    expected = 3.25 + 6.56 * x1 + 3.26 * x2 + 6.72 * x3 + 1.05 * x4
    assert z.value == round(expected, 3) and z.zone == "safe"  # 7.57 > 5.85
    assert fx.altman_z_em(T1).value is None
    assert "retained_earnings" in fx.altman_z_em(T1).missing


def test_beneish_m_by_hand() -> None:
    m = fx.beneish_m(T, T1)
    dsri = (95 / 1000) / (90 / 900)
    gmi = (360 / 900) / (420 / 1000)
    aqi = (1 - (480 + 320) / 1100) / (1 - (400 + 300) / 1000)
    sgi = 1000 / 900
    depi = (30 / (30 + 300)) / (34 / (34 + 320))
    sgai = (105 / 1000) / (100 / 900)
    lvgi = ((260 + 280) / 1100) / ((250 + 300) / 1000)
    tata = (80 - 100) / 1100
    expected = (-4.84 + 0.920 * dsri + 0.528 * gmi + 0.404 * aqi + 0.892 * sgi + 0.115 * depi
                - 0.172 * sgai + 4.679 * tata - 0.327 * lvgi)  # fmt: skip
    assert m.value == round(expected, 3)
    assert m.zone == ("flag" if expected > -2.22 else "clear")
    assert fx.beneish_m(T, None).value is None


def test_cfo_to_pat_and_financials() -> None:
    assert fx.cfo_to_pat(T).value == 1.25
    assert fx.is_financial("Financial Services") and not fx.is_financial("Technology")


def _seed(session: Session, ticker: str, sector: str) -> None:
    session.add(Symbol(ticker=ticker, name=ticker, currency="USD", sector=sector))
    session.commit()
    iid = instrument_ids(session, [ticker])[ticker]
    records = []
    for end, year in ((date(2024, 12, 31), T1), (date(2025, 12, 31), T)):
        for key, value in year.items():
            kind = CONCEPTS[key].kind
            records.append(FactRecord(
                concept=key, period_type="instant" if kind == "stock" else "annual",
                period_end=end, value=value or D(0), unit="USD", currency="USD",
                available_at=date(end.year + 1, 2, 15), point_in_time=True, source="edgar",
                source_concept=key))  # fmt: skip
    record_facts(session, iid, records)
    session.commit()


def test_route_scores_as_known_and_switches_off_for_financials(
    session: Session, client: TestClient
) -> None:
    _seed(session, "ACME", "Technology")
    body = client.get("/v1/symbols/ACME/forensics", params={"as_of": "2026-03-01"}).json()
    assert body["fiscal_year_end"] == "2025-12-31" and body["financial"] is False
    assert body["altman_z"]["zone"] == "safe" and body["cfo_to_pat"]["value"] == 1.25
    assert body["piotroski_known"] == 7  # two years stored: no ROA or turnover change
    # Before the 2025 statements were filed, only fiscal 2024 is known.
    early = client.get("/v1/symbols/ACME/forensics", params={"as_of": "2025-06-01"}).json()
    assert early["fiscal_year_end"] == "2024-12-31"
    _seed(session, "BANKX", "Financial Services")
    bank = client.get("/v1/symbols/BANKX/forensics").json()
    assert bank["financial"] is True and bank["piotroski"] == [] and bank["financial_note"]


@pytest.mark.parametrize("ticker", ["NOPE"])
def test_route_404(client: TestClient, ticker: str) -> None:
    assert client.get(f"/v1/symbols/{ticker}/forensics").status_code == 404
