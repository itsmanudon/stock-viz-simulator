"""A7.4 (M5.3): valuation bands and the reverse DCF."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from stockviz.services.fundamentals import reverse_dcf as rdcf
from stockviz.services.fundamentals.valuation import bands
from tests.test_valuation import _seed


def test_solver_recovers_the_growth_it_was_given() -> None:
    ev = rdcf.present_value(100.0, 0.12, 0.09, 0.03, 10)
    g, reason = rdcf.implied_growth(ev, 100.0, 0.09, 0.03, 10)
    assert reason is None and g == pytest.approx(0.12, abs=1e-6)
    # Back to the price within 0.1%.
    assert g is not None
    assert rdcf.present_value(100.0, g, 0.09, 0.03, 10) == pytest.approx(ev, rel=1e-3)


def test_present_value_by_hand_for_two_years() -> None:
    # F=100, g=10%, w=10%, gt=2%, N=2: 110/1.1 + 121/1.21 + (121 x 1.02 / 0.08) / 1.21.
    expected = 100 + 100 + (121 * 1.02 / 0.08) / 1.21
    assert rdcf.present_value(100.0, 0.10, 0.10, 0.02, 2) == pytest.approx(expected)


@pytest.mark.parametrize(
    ("ev", "fcf", "wacc", "terminal", "needle"),
    [
        (1000.0, -5.0, 0.09, 0.03, "not positive"),
        (1000.0, 10.0, 0.03, 0.03, "above terminal"),
        (1.0, 10.0, 0.09, 0.03, "worth more"),
        (1e12, 10.0, 0.09, 0.03, "more than 100%"),
    ],
)
def test_solver_explains_instead_of_guessing(ev, fcf, wacc, terminal, needle) -> None:
    g, reason = rdcf.implied_growth(ev, fcf, wacc, terminal, 10)
    assert g is None and reason is not None and needle in reason


def test_bands_nearest_rank() -> None:
    values = [float(v) for v in range(1, 21)]  # 1..20
    assert bands(values) == {"p10": 2.0, "p25": 5.0, "p50": 10.0, "p75": 15.0, "p90": 18.0}
    assert bands([1.0, 2.0]) is None


def test_route_solves_with_a_margin_override(session: Session, client: TestClient) -> None:
    _seed(session)  # INFY.NS: EV 80,000, revenue TTM 20,000 (reporting USD)
    body = client.get("/v1/symbols/INFY.NS/reverse-dcf",
                      params={"fcf_margin": 0.2, "as_of": "2026-11-10"}).json()  # fmt: skip
    assert body["base_fcf"] == pytest.approx(4000) and "override" in body["base_fcf_source"]
    g = body["implied_growth"]
    assert rdcf.present_value(4000, g, 0.09, 0.03, 10) == pytest.approx(80_000, rel=1e-3)
    assert len(body["sensitivity"]) == 9
    steps = {s["step"]: s["value"] for s in body["reconciliation"]}
    assert steps["equity_value"] == pytest.approx(72_000) and steps["price"] == pytest.approx(18)
    # No FCF stored and no override: a reason, not a number.
    plain = client.get("/v1/symbols/INFY.NS/reverse-dcf", params={"as_of": "2026-11-10"}).json()
    assert plain["implied_growth"] is None and "No free cash flow" in plain["reason"]


def test_history_carries_bands(session: Session, client: TestClient) -> None:
    _seed(session)
    body = client.get("/v1/symbols/INFY.NS/valuation/history", params={"metric": "pe"}).json()
    assert "bands" in body
