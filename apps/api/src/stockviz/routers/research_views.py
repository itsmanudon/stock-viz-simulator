"""A9 research views on stored data (public, 60/min).

- `GET /v1/symbols/{t}/forecast` (A9.2, M8.2, M8.3)

- `GET /v1/symbols/{t}/seasonality` (A9.1, M3.6)
- `GET /v1/symbols/{t}/earnings-drift` (A9.1, M6.6)
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlmodel import Session

from stockviz.db import get_session
from stockviz.limiter import limiter
from stockviz.models import Symbol
from stockviz.schemas import EarningsDriftOut, ForecastOut, SeasonalityOut
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
