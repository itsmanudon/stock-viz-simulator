"""`GET /v1/symbols/{ticker}/volume-profile` (A6.7, M2.9): a volume profile.

Public, 60/min like the bars route. ``from``/``to`` are instants (naive = UTC;
default the year to now), ``feed`` a stored intraday feed (default the best:
SIP first), ``bins`` 4-200 (default 24) and ``value_area`` 0.05-1 (default
0.7). Built from stored 1-minute bars when they cover every daily session in
the range, else from daily bars (``EOD approximation``); each bar's volume is
spread evenly over its high-low range. The rules are
``services/bars/volume_profile.py``.

- 404: an unknown symbol, or no bars in the range.
- 409: no profile is offered (an index, whose stored volume is 0, or a range
  with no volume), with the reason.
- 422: ``from`` after ``to``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlmodel import Session

from stockviz.db import get_session
from stockviz.limiter import limiter
from stockviz.models import Symbol
from stockviz.schemas import VolumeProfileBinOut, VolumeProfileOut
from stockviz.services.bars.volume_profile import (
    DEFAULT_BINS,
    DEFAULT_VALUE_AREA,
    MAX_BINS,
    MIN_BINS,
    NoBars,
    NoProfile,
    load_profile,
)
from stockviz.services.instruments import resolve_symbol
from stockviz.services.markets.calendar import venue_for_ticker

router = APIRouter(prefix="/v1/symbols", tags=["volume-profile"])

SessionDep = Annotated[Session, Depends(get_session)]


@router.get("/{ticker}/volume-profile", response_model=VolumeProfileOut)
@limiter.limit("60/minute")
def get_volume_profile(
    request: Request,
    ticker: str,
    session: SessionDep,
    from_: Annotated[datetime | None, Query(alias="from")] = None,
    to: Annotated[datetime | None, Query()] = None,
    feed: Annotated[Literal["iex", "sip", "kite", "file", "replayed"] | None, Query()] = None,
    bins: Annotated[int, Query(ge=MIN_BINS, le=MAX_BINS)] = DEFAULT_BINS,
    value_area: Annotated[float, Query(ge=0.05, le=1)] = DEFAULT_VALUE_AREA,
) -> VolumeProfileOut:
    symbol = ticker.upper()
    instrument = resolve_symbol(session, symbol) if session.get(Symbol, symbol) else None
    if instrument is None or instrument.id is None:
        raise HTTPException(status_code=404, detail=f"Symbol {ticker!r} not found")
    try:
        loaded = load_profile(
            session,
            instrument,
            venue=venue_for_ticker(symbol),
            start=from_,
            end=to,
            feed=feed,
            bins=bins,
            value_area=value_area,
        )
    except NoProfile as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except NoBars as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    profile = loaded.profile
    return VolumeProfileOut.model_validate(
        {
            "ticker": symbol,
            "source": loaded.source,
            "feed": loaded.feed,
            "from": loaded.start,
            "to": loaded.end,
            "bars": loaded.bars,
            "bins": [
                VolumeProfileBinOut(low=b.low, high=b.high, volume=round(b.volume, 4))
                for b in profile.bins
            ],
            "poc": profile.poc_price,
            "poc_index": profile.poc,
            "vah": profile.vah,
            "val": profile.val,
            "value_area": value_area,
            "total_volume": profile.total_volume,
            "value_volume": round(profile.value_volume, 4),
            "badges": loaded.badges,
            "note": loaded.note,
        }
    )
