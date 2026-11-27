"""A9.3 (M7.6): the pairs lab, on planted pairs."""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from decimal import Decimal

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from stockviz.models import PriceBar
from stockviz.services import pairs as pr
from tests.symbols import seed_symbols

DAYS = [date(2022, 1, 3) + timedelta(days=i) for i in range(600)]


def _cointegrated(phi: float = 0.9, seed: int = 1) -> list[tuple[date, float, float]]:
    rng = np.random.default_rng(seed)
    lb = np.cumsum(0.01 * rng.normal(size=len(DAYS))) + math.log(50)
    e = np.zeros(len(DAYS))
    for t in range(1, len(DAYS)):
        e[t] = phi * e[t - 1] + 0.01 * rng.normal()
    la = 0.5 + 1.2 * lb + e
    return [(d, math.exp(x), math.exp(y)) for d, x, y in zip(DAYS, la, lb, strict=True)]


def test_planted_pair_rejects_with_its_hedge_ratio_and_half_life() -> None:
    out = pr.pair_stats("A", "B", _cointegrated(phi=0.9))
    assert out.cointegrated_at == "1%"
    assert out.beta == pytest.approx(1.2, abs=0.05)
    # AR(1) with phi 0.9: half-life ln 2 / -ln 0.9 ~ 6.6 sessions (lambda ~ phi - 1).
    assert out.half_life == pytest.approx(math.log(2) / 0.1, rel=0.4)
    assert out.rolling_beta and out.spread and out.zscore is not None


def test_independent_walks_usually_do_not_reject() -> None:
    rejected = 0
    for seed in range(20):
        rng = np.random.default_rng(100 + seed)
        a = np.exp(np.cumsum(0.01 * rng.normal(size=400)) + 4)
        b = np.exp(np.cumsum(0.01 * rng.normal(size=400)) + 4)
        out = pr.pair_stats("A", "B", list(zip(DAYS[:400], a, b, strict=True)))
        rejected += out.cointegrated_at == "5%" or out.cointegrated_at == "1%"
    assert rejected <= 4  # about 5% false positives expected; 20 trials


def test_critical_values_follow_mackinnon() -> None:
    cv = pr.critical_values(500)
    assert cv[0.05] == pytest.approx(-3.33613 - 6.1101 / 500 - 6.823 / 500**2)
    assert cv[0.01] < cv[0.05] < cv[0.10]


def test_short_overlap_has_a_reason() -> None:
    assert pr.pair_stats("A", "B", _cointegrated()[:50]).reason


def test_route(session: Session, client: TestClient) -> None:
    rows = _cointegrated(seed=4)
    for ticker, col in (("AAA", 1), ("BBB", 2)):
        seed_symbols(session, ticker, currency="USD")
        for row in rows:
            price = Decimal(f"{row[col]:.6f}")
            session.add(PriceBar(ticker=ticker, ts=datetime.combine(row[0], datetime.min.time()),
                                 interval="1d", open=price, high=price, low=price, close=price,
                                 volume=1, source="test"))  # fmt: skip
    session.commit()
    body = client.get("/v1/symbols/AAA/pair/BBB", params={"years": 2}).json()
    assert body["cointegrated_at"] in ("1%", "5%") and "MacKinnon" in body["method"]
    assert body["sessions"] <= 2 * 366
    assert client.get("/v1/symbols/AAA/pair/AAA").status_code == 400
