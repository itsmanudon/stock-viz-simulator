"""A9.13 (M8.5): option-implied vs model distribution."""

from __future__ import annotations

import math
from datetime import date, timedelta
from decimal import Decimal

import numpy as np
from fastapi.testclient import TestClient
from sqlmodel import Session

from stockviz.models.option_quote import OptionChainQuote
from stockviz.services.instruments import instrument_ids
from stockviz.services.options import implied_distribution as idist
from tests.symbols import seed_symbols
from tests.test_a35_chart_context import _bars

T = 30 / 365


def _flat(iv: float = 0.25) -> list[idist.SmilePoint]:
    return [idist.SmilePoint(float(k), iv) for k in range(60, 141, 5)]


def test_a_flat_smile_gives_back_the_lognormal() -> None:
    d = idist.distribution(_flat(), spot=100, t=T, r=0.04, model_vol=0.25, model_vol_source="x")
    assert d.reason is None and d.implied_atm_vol == 0.25
    for a, b in zip(d.implied_quantiles, d.model_quantiles, strict=True):
        assert abs(a - b) < 0.05
    assert d.implied_p_down is not None and d.model_p_down is not None
    assert abs(d.implied_p_down - d.model_p_down) < 0.002
    assert len(d.curve) == idist.CURVE_POINTS and (d.negative_mass or 0) < 1e-6
    # The median of a lognormal with that forward, by hand.
    median = 100 * math.exp((0.04 - 0.25**2 / 2) * T)
    assert abs(d.implied_quantiles[2] - median) < 0.05


def test_put_skew_fattens_the_left_tail() -> None:
    skew = [idist.SmilePoint(p.strike, 0.25 + 0.004 * (100 - p.strike)) for p in _flat()]
    d = idist.distribution(skew, spot=100, t=T, r=0.04, model_vol=0.25, model_vol_source="x")
    assert d.implied_p_down and d.model_p_down and d.implied_p_down > d.model_p_down
    assert d.implied_quantiles[0] < d.model_quantiles[0]


def test_refusals_and_the_smile() -> None:
    few = [idist.SmilePoint(95, 0.2), idist.SmilePoint(105, 0.2)]
    assert "at least 5" in (idist.distribution(few, spot=100, t=T, r=0.0, model_vol=None,
                                                model_vol_source=None).reason or "")  # fmt: skip
    one_sided = [idist.SmilePoint(float(k), 0.2) for k in range(101, 120)]
    assert idist.distribution(
        one_sided, spot=100, t=T, r=0, model_vol=None, model_vol_source=None
    ).reason
    pts = idist.smile([(90, "put", 0.3), (90, "call", 0.9), (100, "put", 0.2), (100, "call", 0.22),
                       (110, "call", 0.18), (110, "put", 0.7), (120, "call", -1.0)], 100)  # fmt: skip
    assert [(p.strike, round(p.iv, 3)) for p in pts] == [(90, 0.3), (100, 0.21), (110, 0.18)]
    d = idist.distribution(_flat(), spot=100, t=T, r=0.04, model_vol=None, model_vol_source=None)
    assert d.implied_quantiles and d.model_quantiles == [] and d.model_p_down is None
    assert np.isclose(sum(c[2] for c in d.curve), 0)


def test_route(client: TestClient, session: Session) -> None:
    seed_symbols(session, "ACME")
    start = date(2025, 1, 1)
    rng = np.random.default_rng(3)
    closes = list(100 * np.exp(np.cumsum(rng.normal(0, 0.015, 320))))
    _bars(session, "ACME", [float(c) for c in closes], start)
    iid = instrument_ids(session, ["ACME"])["ACME"]
    from sqlmodel import col, select

    from stockviz.models import PriceBar

    last = session.exec(select(PriceBar).where(col(PriceBar.ticker) == "ACME")
                        .order_by(col(PriceBar.ts).desc())).first()  # fmt: skip
    assert last is not None
    snap, spot = last.ts.date(), float(last.close)
    for days in (9, 30, 60):
        for k in np.linspace(spot * 0.7, spot * 1.3, 13):
            for kind in ("put", "call"):
                session.add(OptionChainQuote(
                    instrument_id=iid, snapshot_date=snap, expiry=snap + timedelta(days=days),
                    strike=Decimal(str(round(float(k), 2))), option_type=kind,
                    implied_volatility=0.3,
                ))  # fmt: skip
    session.commit()
    res = client.get("/v1/options/acme/implied-distribution")
    assert res.status_code == 200, res.text
    got = res.json()
    assert got["days"] == 30 and got["reason"] is None and got["implied_atm_vol"] == 0.3
    assert got["model_vol_source"] and got["model_vol"] > 0
    assert len(got["implied_quantiles"]) == 5 and len(got["curve"]) == idist.CURVE_POINTS
    assert "risk premium" in got["method"]
    picked = client.get("/v1/options/ACME/implied-distribution",
                        params={"expiry": str(snap + timedelta(days=60))}).json()  # fmt: skip
    assert picked["days"] == 60
    seed_symbols(session, "NOCH")
    assert "No option chain" in client.get("/v1/options/NOCH/implied-distribution").json()["reason"]
    assert client.get("/v1/options/NOPE/implied-distribution").status_code == 404


def test_noisy_quotes_are_smoothed() -> None:
    """Outliers like yfinance's deep out-of-the-money IVs barely move the fit."""
    rng = np.random.default_rng(1)
    pts = [idist.SmilePoint(float(k), 0.25 + 0.003 * (100 - k) + float(rng.normal(0, 0.01)))
           for k in range(70, 131, 2)]  # fmt: skip
    pts += [idist.SmilePoint(40.0, 2.9), idist.SmilePoint(170.0, 0.01), idist.SmilePoint(99.0, 5.0)]
    d = idist.distribution(pts, spot=100, t=T, r=0.04, model_vol=0.25, model_vol_source="x")
    assert d.reason is None and abs((d.implied_atm_vol or 0) - 0.25) < 0.01
    assert (d.negative_mass or 0) < 0.01
