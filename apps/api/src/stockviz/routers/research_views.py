"""A9 research views on stored data (public, 60/min).

- `GET /v1/symbols/{t}/forecast` (A9.2, M8.2, M8.3)
- `GET /v1/symbols/{a}/pair/{b}` (A9.3, M7.6)
- `GET /v1/symbols/{t}/structure` (A9.5, M2.12)

- `GET /v1/symbols/{t}/seasonality` (A9.1, M3.6)
- `GET /v1/symbols/{t}/earnings-drift` (A9.1, M6.6)
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlmodel import Session

from stockviz.db import get_session
from stockviz.limiter import limiter
from stockviz.models import Symbol
from stockviz.schemas import (
    EarningsDriftOut,
    ForecastOut,
    LenderOut,
    LenderPeerOut,
    PairOut,
    SeasonalityOut,
    StructureOut,
)
from stockviz.services import lender as lender_svc
from stockviz.services import seasonality as svc

router = APIRouter(prefix="/v1/symbols", tags=["research"])

SessionDep = Annotated[Session, Depends(get_session)]

SEASON_NOTE = (
    "Stored history, percent returns. Association, not a forecast: a month's average "
    "can be one big year; months under 10 years of data are marked thin."
)
DRIFT_NOTE = (
    "Reaction: the first session after the report (before the open: that day; after the "
    "close: the next; unknown time: the event day, marked assumed). Drift is measured from "
    "the reaction close."
)


def _symbol(session: Session, ticker: str) -> str:
    ticker = ticker.upper()
    if session.get(Symbol, ticker) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Symbol {ticker!r} not found")
    return ticker


@router.get("/{ticker}/seasonality", response_model=SeasonalityOut)
@limiter.limit("60/minute")
def get_seasonality(request: Request, ticker: str, session: SessionDep) -> SeasonalityOut:
    del request
    ticker = _symbol(session, ticker)
    result = svc.seasonality(svc.closes(session, ticker))
    return SeasonalityOut.model_validate({"ticker": ticker, "note": SEASON_NOTE, **result})


@router.get("/{ticker}/earnings-drift", response_model=EarningsDriftOut)
@limiter.limit("60/minute")
def get_earnings_drift(request: Request, ticker: str, session: SessionDep) -> EarningsDriftOut:
    del request
    ticker = _symbol(session, ticker)
    d = svc.earnings_drift(svc.closes(session, ticker), svc.events_for(session, ticker))
    return EarningsDriftOut.model_validate({
        "ticker": ticker, "note": DRIFT_NOTE, "avg_abs_reaction": d.avg_abs_reaction,
        "avg_abs_day": d.avg_abs_day, "events": d.events, "groups": d.groups,
    })  # fmt: skip


FORECAST_METHOD = {
    "har": "HAR-RV (Corsi 2009) on Parkinson daily variance, fitted on earlier days only",
    "scoring": "Last 250 sessions out of sample; skill = 1 - loss(HAR) / loss(random walk: "
    "tomorrow = today); above 0 beats it",
    "cones": "Split-conformal bands around a zero-drift random walk from the previous 250 "
    "completed moves; realised coverage over the last 250 sessions beside each level",
    "honesty": "A volatility forecast, not a price target; coverage below the level means "
    "the bands were too narrow",
}


@router.get("/{ticker}/forecast", response_model=ForecastOut)
@limiter.limit("30/minute")
def get_forecast(request: Request, ticker: str, session: SessionDep) -> ForecastOut:
    """A9.2: every forecast with its skill against a random walk and its coverage."""
    import numpy as np

    from stockviz.services import forecasts as fc
    from stockviz.services.seasonality import bars_hlc

    del request
    ticker = _symbol(session, ticker)
    dates, high, low, close = bars_hlc(session, ticker)
    vol = fc.har_forecast(np.array(high), np.array(low)) if dates else fc.VolForecast(
        reason="No stored bars.")  # fmt: skip
    cones = fc.price_cones(dates, np.array(close)) if dates else fc.PriceCones(None, None,
                                                                                 reason="No stored bars.")  # fmt: skip
    return ForecastOut.model_validate({
        "ticker": ticker, "last_date": cones.last_date, "last_close": cones.last_close,
        "volatility": vol.__dict__, "cones": [c.__dict__ for c in cones.cones],
        "cones_reason": cones.reason, "method": FORECAST_METHOD,
    })  # fmt: skip


PAIR_METHOD = (
    "Engle-Granger: OLS hedge ratio on log closes over the common sessions, then an ADF "
    "test (one lag) on the residual against MacKinnon (2010) critical values for two "
    "variables with a constant. Not rejecting means no evidence of cointegration; a "
    "cointegrated past is no promise."
)


@router.get("/{ticker}/pair/{other}", response_model=PairOut)
@limiter.limit("30/minute")
def get_pair(
    request: Request, ticker: str, other: str, session: SessionDep, years: int = 3
) -> PairOut:
    """A9.3: cointegration, hedge ratio, half-life and the spread's z-score."""
    from datetime import timedelta

    from stockviz.services.pairs import pair_stats

    del request
    a, b = _symbol(session, ticker), _symbol(session, other)
    if a == b:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "pick two different symbols")
    if not 1 <= years <= 15:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "years is 1 to 15")
    ca = dict(svc.closes(session, a))
    cb = dict(svc.closes(session, b))
    common = sorted(set(ca) & set(cb))
    if common:
        cutoff = common[-1] - timedelta(days=365 * years)
        common = [d for d in common if d >= cutoff]
    result = pair_stats(a, b, [(d, ca[d], cb[d]) for d in common])
    return PairOut.model_validate({**result.__dict__, "method": PAIR_METHOD})


@router.get("/{ticker}/structure", response_model=StructureOut)
@limiter.limit("60/minute")
def get_structure(
    request: Request, ticker: str, session: SessionDep, n: int = 5, sessions: int = 250
) -> StructureOut:
    """A9.5: pivots, labels and zones over the last ``sessions`` daily bars."""
    from stockviz.services.structure import Bar, structure

    del request
    ticker = _symbol(session, ticker)
    if not 2 <= n <= 20 or not 30 <= sessions <= 2000:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "n is 2-20 and sessions 30-2000")
    dates, high, low, close = svc.bars_hlc(session, ticker)
    bars = [Bar(d, h, lo, c) for d, h, lo, c in zip(dates, high, low, close, strict=True)][
        -sessions:
    ]
    result = structure(bars, n)
    return StructureOut.model_validate({"ticker": ticker, "sessions": len(bars), **result.__dict__})


@router.get("/{ticker}/lender", response_model=LenderOut)
@limiter.limit("60/minute")
def get_lender(
    request: Request,
    ticker: str,
    session: SessionDep,
    coe: Annotated[float | None, Query(gt=0, le=0.4)] = None,
    growth: Annotated[float | None, Query(ge=-0.1, le=0.3)] = None,
) -> LenderOut:
    """A7.13 (M5.2): lender mode, P/B against ROE (409 for a non-financial symbol)."""
    del request
    ticker = _symbol(session, ticker)
    try:
        view = lender_svc.lender_view(session, ticker, coe=coe, growth=growth)
    except lender_svc.NotALender as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return LenderOut(
        ticker=view.ticker,
        market=view.market,
        pb=view.pb,
        roe=view.roe,
        as_of=view.as_of,
        peers=[LenderPeerOut(ticker=p.ticker, pb=p.pb, roe=p.roe) for p in view.peers],
        slope=view.slope,
        intercept=view.intercept,
        line_pb=view.line_pb,
        gap=view.gap,
        coe=view.coe,
        growth=view.growth,
        justified_pb=view.justified_pb,
        reasons=view.reasons,
        method=" ".join((lender_svc.__doc__ or "").split("\n\n", 1)[-1].split()),
        kpi_note=lender_svc.KPI_NOTE,
    )
