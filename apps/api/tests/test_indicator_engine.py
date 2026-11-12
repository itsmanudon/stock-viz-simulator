"""Phase 6.1: the indicator engine against its definitions, and warm-up (RS-1).

Each indicator is checked against a plain loop written from its textbook
definition on a seeded random OHLCV series, plus small cases worked by hand.
"""

# The reference loops use float | None lists (None before the first value).
# pyright: reportOperatorIssue=false, reportArgumentType=false, reportOptionalOperand=false

from __future__ import annotations

import math
import random
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from stockviz.models import PriceBar
from stockviz.services.indicators import engine
from tests.symbols import seed_symbols

N = 400


def _series(seed: int = 11):
    rng = random.Random(seed)
    rows, price = [], 100.0
    start = datetime(2024, 1, 1)
    for i in range(N):
        o = price
        c = max(1.0, o * (1 + rng.gauss(0, 0.02)))
        h = max(o, c) * (1 + abs(rng.gauss(0, 0.01)))
        lo = min(o, c) * (1 - abs(rng.gauss(0, 0.01)))
        v = rng.randint(1_000, 50_000)
        rows.append((start + timedelta(days=i), o, h, lo, c, v))
        price = c
    return rows


ROWS = _series()
F = engine.frame(ROWS)
OPENS = [r[1] for r in ROWS]
H = [r[2] for r in ROWS]
L = [r[3] for r in ROWS]
C = [r[4] for r in ROWS]
V = [r[5] for r in ROWS]


def _close(a, b, tol=1e-9):
    if a is None or (isinstance(a, float) and math.isnan(a)):
        return b is None or (isinstance(b, float) and math.isnan(b))
    return b is not None and not math.isnan(b) and abs(a - b) <= tol * max(1.0, abs(b))


def _check(series, expected, tol=1e-9):
    got = series.tolist()
    assert len(got) == len(expected)
    bad = [i for i, (g, e) in enumerate(zip(got, expected, strict=True)) if not _close(g, e, tol)]
    assert not bad, (bad[:5], [got[i] for i in bad[:3]], [expected[i] for i in bad[:3]])


def _wilder(values, n):
    out = [None] * len(values)
    idx = [i for i, v in enumerate(values) if v is not None]
    if len(idx) < n:
        return out
    first = idx[n - 1]
    out[first] = sum(values[i] for i in idx[:n]) / n
    for i in range(first + 1, len(values)):
        out[i] = (out[i - 1] * (n - 1) + values[i]) / n
    return out


def _sma(values, n):
    return [
        None
        if i < n - 1 or any(v is None for v in values[i - n + 1 : i + 1])
        else sum(values[i - n + 1 : i + 1]) / n
        for i in range(len(values))
    ]


def _tr():
    return [H[0] - L[0]] + [
        max(H[i] - L[i], abs(H[i] - C[i - 1]), abs(L[i] - C[i - 1])) for i in range(1, N)
    ]


def test_sma_wma_roc_against_loops() -> None:
    _check(engine.sma(F, 20)["value"], _sma(C, 20))
    w = list(range(1, 11))
    _check(
        engine.wma(F, 10)["value"],
        [
            None if i < 9 else sum(a * b for a, b in zip(C[i - 9 : i + 1], w, strict=True)) / sum(w)
            for i in range(N)
        ],
    )
    _check(
        engine.roc(F, 12)["value"],
        [None if i < 12 else 100 * (C[i] / C[i - 12] - 1) for i in range(N)],
    )


def test_rsi_atr_are_wilder() -> None:
    gains = [None] + [max(C[i] - C[i - 1], 0) for i in range(1, N)]
    losses = [None] + [max(C[i - 1] - C[i], 0) for i in range(1, N)]
    ag, al = _wilder(gains, 14), _wilder(losses, 14)
    expected = [
        None if a is None else (100.0 if b == 0 else 100 - 100 / (1 + a / b))
        for a, b in zip(ag, al, strict=True)
    ]
    _check(engine.rsi(F, 14)["value"], expected)
    _check(engine.atr(F, 14)["value"], _wilder(_tr(), 14))


def test_bands_and_channels() -> None:
    mid = _sma(C, 20)
    sd = [
        None if m is None else math.sqrt(sum((x - m) ** 2 for x in C[i - 19 : i + 1]) / 20)
        for i, m in enumerate(mid)
    ]
    b = engine.bb(F, 20, 2.0)
    _check(b["upper"], [None if m is None else m + 2 * s for m, s in zip(mid, sd, strict=True)])
    _check(b["lower"], [None if m is None else m - 2 * s for m, s in zip(mid, sd, strict=True)])
    d = engine.donchian(F, 20)
    _check(d["upper"], [None if i < 19 else max(H[i - 19 : i + 1]) for i in range(N)])
    _check(d["lower"], [None if i < 19 else min(L[i - 19 : i + 1]) for i in range(N)])


def test_stochastic_williams_cci() -> None:
    k = [
        None
        if i < 13
        else 100
        * (C[i] - min(L[i - 13 : i + 1]))
        / (max(H[i - 13 : i + 1]) - min(L[i - 13 : i + 1]))
        for i in range(N)
    ]
    s = engine.stoch(F, 14, 3)
    _check(s["k"], k)
    _check(s["d"], _sma(k, 3))
    _check(
        engine.willr(F, 14)["value"],
        [
            None
            if i < 13
            else -100
            * (max(H[i - 13 : i + 1]) - C[i])
            / (max(H[i - 13 : i + 1]) - min(L[i - 13 : i + 1]))
            for i in range(N)
        ],
    )
    tp = [(h + lo + c) / 3 for h, lo, c in zip(H, L, C, strict=True)]
    cci = []
    for i in range(N):
        if i < 19:
            cci.append(None)
            continue
        window = tp[i - 19 : i + 1]
        mean = sum(window) / 20
        mad = sum(abs(x - mean) for x in window) / 20
        cci.append((tp[i] - mean) / (0.015 * mad))
    _check(engine.cci(F, 20)["value"], cci, tol=1e-8)


def test_volume_indicators() -> None:
    obv = [0.0]
    for i in range(1, N):
        sign = (C[i] > C[i - 1]) - (C[i] < C[i - 1])
        obv.append(obv[-1] + sign * V[i])
    _check(engine.obv(F)["value"], obv)
    tp = [(h + lo + c) / 3 for h, lo, c in zip(H, L, C, strict=True)]
    mfi = []
    for i in range(N):
        if i < 14:
            mfi.append(None)
            continue
        pos = sum(tp[j] * V[j] for j in range(i - 13, i + 1) if tp[j] > tp[j - 1])
        neg = sum(tp[j] * V[j] for j in range(i - 13, i + 1) if tp[j] < tp[j - 1])
        mfi.append(100.0 if neg == 0 else 100 - 100 / (1 + pos / neg))
    _check(engine.mfi(F, 14)["value"], mfi)
    _check(
        engine.rvol(F, 20)["value"],
        [None if i < 20 else V[i] / (sum(V[i - 20 : i]) / 20) for i in range(N)],
    )


def test_adx_against_wilder_loop() -> None:
    plus_dm, minus_dm, tr = [None], [None], [None]
    for i in range(1, N):
        up, down = H[i] - H[i - 1], L[i - 1] - L[i]
        plus_dm.append(up if up > down and up > 0 else 0.0)
        minus_dm.append(down if down > up and down > 0 else 0.0)
        tr.append(max(H[i] - L[i], abs(H[i] - C[i - 1]), abs(L[i] - C[i - 1])))
    trn, pdm, mdm = _wilder(tr, 14), _wilder(plus_dm, 14), _wilder(minus_dm, 14)
    pdi = [None if t is None else 100 * p / t for p, t in zip(pdm, trn, strict=True)]
    mdi = [None if t is None else 100 * m / t for m, t in zip(mdm, trn, strict=True)]
    dx = [None if p is None else 100 * abs(p - m) / (p + m) for p, m in zip(pdi, mdi, strict=True)]
    out = engine.adx(F, 14)
    _check(out["plus_di"], pdi)
    _check(out["adx"], _wilder(dx, 14))


def test_hand_cases() -> None:
    flat = engine.frame([(datetime(2024, 1, d), 10, 10, 10, 10, 100) for d in range(1, 30)])
    assert engine.sma(flat, 5)["value"].iloc[-1] == 10
    assert engine.atr(flat, 5)["value"].iloc[-1] == 0
    rising = engine.frame([(datetime(2024, 1, d), d, d, d, d, 100) for d in range(1, 30)])
    assert engine.rsi(rising, 14)["value"].iloc[-1] == 100  # no losses at all
    # Bollinger of a constant is a zero-width band at the constant.
    band = engine.bb(flat, 5, 2.0)
    assert band["upper"].iloc[-1] == band["lower"].iloc[-1] == 10
    st = engine.supertrend(rising, 3, 1.0)
    assert st["direction"].iloc[-1] == 1  # a steady rise is an uptrend


def test_parse_and_lookbacks() -> None:
    assert engine.parse("rsi_14").lookback == 140
    assert engine.parse("BB_20_2.5").args == (20, 2.5)
    assert engine.parse("macd").args == (12, 26, 9)
    for bad in ("nope_3", "sma_0", "sma_20_5", "bb_20_99"):
        with pytest.raises(ValueError):
            engine.parse(bad)


# --- RS-1: a value does not depend on the window requested -----------------


def _seed(session: Session) -> None:
    seed_symbols(session, "AAPL")
    for ts, o, h, lo, c, v in ROWS:
        session.add(
            PriceBar(
                ticker="AAPL",
                ts=ts,
                interval="1d",
                open=Decimal(str(round(o, 4))),
                high=Decimal(str(round(h, 4))),
                low=Decimal(str(round(lo, 4))),
                close=Decimal(str(round(c, 4))),
                volume=v,
                source="test",
            )
        )
    session.commit()


def test_one_month_and_one_year_agree(session: Session, client: TestClient) -> None:
    _seed(session)
    names = "rsi_14,sma_200,bb_20_2,atr_14,macd"
    month = client.get(f"/v1/symbols/AAPL/indicators?names={names}&limit=22").json()
    year = client.get(f"/v1/symbols/AAPL/indicators?names={names}&limit=252").json()

    assert month["warmup_bars"] >= 140
    assert month["meta"]["rsi_14"]["pane"] == "separate"
    assert month["meta"]["bb_20_2"]["outputs"] == ["upper", "middle", "lower"]
    for key in ("rsi_14", "sma_200", "bb_20_2.upper", "atr_14"):
        last_month = month["series"][key][-1]
        last_year = year["series"][key][-1]
        assert last_month["ts"] == last_year["ts"]
        assert last_month["value"] == pytest.approx(last_year["value"], rel=1e-4), key
        assert len(month["series"][key]) == 22  # values for the whole window, none before
    assert month["macd"][-1]["histogram"] == pytest.approx(
        year["macd"][-1]["histogram"], rel=1e-3, abs=1e-6
    )
    catalog = client.get("/v1/indicators/catalog").json()
    assert {c["key"] for c in catalog} >= {"rsi", "macd", "bb", "atr", "adx", "obv", "supertrend"}
