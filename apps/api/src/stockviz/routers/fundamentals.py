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
    FundamentalRowOut,
    FundamentalsOut,
    ValuationHistoryOut,
    ValuationMetricOut,
    ValuationOut,
    ValuationPointOut,
)
from stockviz.services.fundamentals.concepts import CONCEPTS
from stockviz.services.fundamentals.store import facts_as_of
from stockviz.services.fundamentals.valuation import history, valuation
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
    )
