"""`/v1/symbols/{ticker}/fundamentals` — statements as known on a date (Phase 6.3).

Columns are the latest ``periods`` annual or quarterly period ends; rows are
the normalised concepts (``services/fundamentals/concepts.py``). Balance-sheet
lines are read at each period's end. Every figure is the version known on
``as_of`` (default today), so a past date shows what was public then, to the
extent the source records it (``point_in_time``).
"""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlmodel import Session

from stockviz._time import utcnow
from stockviz.db import get_session
from stockviz.limiter import limiter
from stockviz.models import Symbol
from stockviz.schemas import (
    ForensicScoreOut,
    ForensicsOut,
    ForensicTestOut,
    FundamentalRowOut,
    FundamentalsOut,
    ReverseDcfOut,
    ReverseDcfRowOut,
    ReverseDcfStepOut,
    ValuationHistoryOut,
    ValuationMetricOut,
    ValuationOut,
    ValuationPointOut,
)
from stockviz.services.fundamentals import forensics as fx
from stockviz.services.fundamentals import reverse_dcf as rdcf
from stockviz.services.fundamentals.concepts import CONCEPTS
from stockviz.services.fundamentals.store import facts_as_of
from stockviz.services.fundamentals.valuation import bands, history, valuation
from stockviz.services.instruments import instrument_ids

router = APIRouter(prefix="/v1/symbols", tags=["fundamentals"])

SessionDep = Annotated[Session, Depends(get_session)]


@router.get("/{ticker}/fundamentals", response_model=FundamentalsOut)
@limiter.limit("60/minute")
def get_fundamentals(
    request: Request,
    ticker: str,
    session: SessionDep,
    period: Annotated[str, Query(pattern="^(annual|quarter)$")] = "annual",
    as_of: Annotated[date | None, Query()] = None,
    periods: Annotated[int, Query(ge=1, le=20)] = 5,
) -> FundamentalsOut:
    ticker = ticker.upper()
    if session.get(Symbol, ticker) is None:
        raise HTTPException(status_code=404, detail=f"Symbol {ticker!r} not found")
    day = as_of or utcnow().date()
    instrument_id = instrument_ids(session, [ticker]).get(ticker)
    known = facts_as_of(session, instrument_id, day) if instrument_id is not None else {}

    ends = sorted({end for (_c, ptype, end) in known if ptype == period}, reverse=True)[:periods]
    rows: list[FundamentalRowOut] = []
    used = []
    for key, concept in CONCEPTS.items():
        ptype = "instant" if concept.kind == "stock" else period
        facts = [known.get((key, ptype, end)) for end in ends]
        if not any(facts):
            continue
        used.extend(f for f in facts if f is not None)
        unit = next(f.unit for f in facts if f is not None)
        rows.append(
            FundamentalRowOut(
                concept=key,
                label=concept.label,
                unit=unit,
                values=[f.value if f is not None else None for f in facts],
            )
        )
    currencies = {f.currency for f in used if f.currency}
    return FundamentalsOut(
        ticker=ticker,
        period=period,  # type: ignore[arg-type]
        as_of=day,
        currency=currencies.pop() if len(currencies) == 1 else None,
        periods=ends,
        rows=rows,
        sources=sorted({f.source for f in used}),
        point_in_time=bool(used) and all(f.point_in_time for f in used),
        latest_available_at=max((f.available_at for f in used), default=None),
    )


HISTORY_METRICS = ("pe", "pb", "ps", "ev_ebitda", "ev_revenue", "p_fcf", "dividend_yield")


@router.get("/{ticker}/valuation", response_model=ValuationOut)
@limiter.limit("60/minute")
def get_valuation(
    request: Request,
    ticker: str,
    session: SessionDep,
    as_of: Annotated[date | None, Query()] = None,
) -> ValuationOut:
    """Multiples and quality metrics as known on ``as_of`` (Phase 6.4)."""
    ticker = ticker.upper()
    if session.get(Symbol, ticker) is None:
        raise HTTPException(status_code=404, detail=f"Symbol {ticker!r} not found")
    v = valuation(session, ticker, as_of or utcnow().date())
    return ValuationOut(
        ticker=v.ticker,
        as_of=v.as_of,
        price=v.price,
        price_date=v.price_date,
        trading_currency=v.trading_currency,
        reporting_currency=v.reporting_currency,
        fx_rate=v.fx_rate,
        basis=v.basis,  # type: ignore[arg-type]
        point_in_time=v.point_in_time,
        sources=v.sources,
        metrics=[
            ValuationMetricOut(
                key=m.key, label=m.label, value=m.value, unit=m.unit, reason=m.reason
            )
            for m in v.metrics
        ],
    )


@router.get("/{ticker}/valuation/history", response_model=ValuationHistoryOut)
@limiter.limit("20/minute")
def get_valuation_history(
    request: Request,
    ticker: str,
    session: SessionDep,
    metric: Annotated[str, Query(pattern="^(" + "|".join(HISTORY_METRICS) + ")$")] = "pe",
    years: Annotated[int, Query(ge=1, le=10)] = 5,
) -> ValuationHistoryOut:
    """Month-end values of one multiple, each computed as known on that day."""
    ticker = ticker.upper()
    if session.get(Symbol, ticker) is None:
        raise HTTPException(status_code=404, detail=f"Symbol {ticker!r} not found")
    points, percentile = history(session, ticker, metric, end=utcnow().date(), years=years)
    return ValuationHistoryOut(
        ticker=ticker,
        metric=metric,
        points=[ValuationPointOut(date=d, value=v) for d, v in points],
        percentile=percentile,
        bands=bands([v for _d, v in points]),
    )


FORENSICS_METHOD = {
    "piotroski": "Nine pass/fail tests (Piotroski 2000) on fiscal year t against t-1; "
    "the score counts passes among the tests that could be judged",
    "altman_z": "Emerging-market Z'' (Altman 2005): 3.25 + 6.56 X1 + 3.26 X2 + 6.72 X3 + "
    "1.05 X4; safe above 5.85, distress below 4.35",
    "beneish_m": "Eight-variable M-score (Beneish 1999); flagged above -2.22",
    "cfo_to_pat": "Operating cash flow / net income, year t",
    "point_in_time": "Annual facts as known on as_of (filing dates); missing fields are "
    "named, never guessed",
}


def _score(score: fx.Score) -> ForensicScoreOut:
    return ForensicScoreOut(value=score.value, zone=score.zone, missing=list(score.missing),
                            parts=dict(score.parts))  # fmt: skip


@router.get("/{ticker}/forensics", response_model=ForensicsOut)
@limiter.limit("60/minute")
def get_forensics(
    request: Request,
    ticker: str,
    session: SessionDep,
    as_of: Annotated[date | None, Query()] = None,
) -> ForensicsOut:
    """A7.3 (M5.1, M5.2): Piotroski, Altman Z'' and Beneish on the latest fiscal
    years known on ``as_of``; financial companies get none of them."""
    ticker = ticker.upper()
    symbol = session.get(Symbol, ticker)
    if symbol is None:
        raise HTTPException(status_code=404, detail=f"Symbol {ticker!r} not found")
    day = as_of or utcnow().date()
    out = ForensicsOut(ticker=ticker, as_of=day, sector=symbol.sector,
                       financial=fx.is_financial(symbol.sector), method=FORENSICS_METHOD)  # fmt: skip
    if out.financial:
        out.financial_note = (
            "A financial company: Piotroski, Altman and Beneish were built on non-financial "
            "firms and misread a lender's balance sheet, so they are not shown."
        )
        return out
    instrument_id = instrument_ids(session, [ticker]).get(ticker)
    known = facts_as_of(session, instrument_id, day, period_types=("annual", "instant")) if (
        instrument_id is not None) else {}  # fmt: skip
    ends = sorted({end for (_c, ptype, end) in known if ptype == "annual"}, reverse=True)[:3]
    if not ends:
        out.reason = "No annual statements stored for this symbol."
        return out
    years: list[dict[str, object]] = []
    currencies: set[str] = set()
    for end in ends:
        year: dict[str, object] = {}
        for key, concept in CONCEPTS.items():
            fact = known.get((key, "instant" if concept.kind == "stock" else "annual", end))
            if fact is not None:
                year[key] = fact.value
                if fact.currency:
                    currencies.add(fact.currency)
        years.append(year)
    t, t1, t2 = [*years, None, None][:3]
    assert t is not None
    out.fiscal_year_end = ends[0]
    out.previous_year_end = ends[1] if len(ends) > 1 else None
    out.currency = next(iter(currencies)) if len(currencies) == 1 else None
    p = fx.piotroski(t, t1, t2)  # type: ignore[arg-type]
    out.piotroski_score, out.piotroski_known = p.score, p.known
    out.piotroski = [ForensicTestOut(key=x.key, label=x.label, result=x.result,  # type: ignore[arg-type]
                                     detail=x.detail) for x in p.tests]  # fmt: skip
    out.altman_z = _score(fx.altman_z_em(t))  # type: ignore[arg-type]
    out.beneish_m = _score(fx.beneish_m(t, t1))  # type: ignore[arg-type]
    out.cfo_to_pat = _score(fx.cfo_to_pat(t))  # type: ignore[arg-type]
    return out


REVERSE_DCF_METHOD = (
    "Two-stage DCF: N years of free cash flow growing at g, then Gordon growth at the "
    "terminal rate, discounted at WACC; g is solved (bisection) so the value equals today's "
    "enterprise value. Market-implied, not a forecast."
)


def _num(value) -> float | None:  # Decimal | None -> float | None
    return None if value is None else float(value)


@router.get("/{ticker}/reverse-dcf", response_model=ReverseDcfOut)
@limiter.limit("60/minute")
def get_reverse_dcf(
    request: Request,
    ticker: str,
    session: SessionDep,
    wacc: Annotated[float, Query(gt=0.0, le=0.3)] = 0.09,
    terminal_growth: Annotated[float, Query(ge=-0.02, le=0.06)] = 0.03,
    years: Annotated[int, Query(ge=3, le=20)] = 10,
    fcf_margin: Annotated[float | None, Query(gt=-1.0, le=1.0)] = None,
    as_of: Annotated[date | None, Query()] = None,
) -> ReverseDcfOut:
    """A7.4 (M5.3): the growth the price implies, with a sensitivity grid."""
    ticker = ticker.upper()
    if session.get(Symbol, ticker) is None:
        raise HTTPException(status_code=404, detail=f"Symbol {ticker!r} not found")
    day = as_of or utcnow().date()
    v = valuation(session, ticker, day)
    r = rdcf.reverse_dcf(
        enterprise_value=_num(v.enterprise_value), fcf_ttm=_num(v.fcf_ttm),
        revenue_ttm=_num(v.revenue_ttm), fcf_margin=fcf_margin, wacc=wacc,
        terminal_growth=terminal_growth, years=years, debt=_num(v.debt), cash=_num(v.cash),
        shares=_num(v.shares),
    )  # fmt: skip
    return ReverseDcfOut(
        ticker=ticker, as_of=day, currency=v.reporting_currency,
        implied_growth=None if r.implied_growth is None else round(r.implied_growth, 6),
        reason=r.reason, base_fcf=r.base_fcf, base_fcf_source=r.base_fcf_source, wacc=wacc,
        terminal_growth=terminal_growth, years=years, enterprise_value=r.enterprise_value,
        sensitivity=[ReverseDcfRowOut(**row) for row in r.grid],  # type: ignore[arg-type]
        reconciliation=[ReverseDcfStepOut(step=k, value=val) for k, val in r.reconciliation],
        method=REVERSE_DCF_METHOD,
    )  # fmt: skip
