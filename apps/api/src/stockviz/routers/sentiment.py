"""`/v1/symbols/{ticker}/sentiment` — daily mean news sentiment.

Since Phase 2 the source is Aegis News, read from the copied tables
(audit AG-14). Days are bucketed by each analysis's ``available_at`` (UTC),
the time Aegis knew the score, never by the publisher's date.

Public and rate-limited like the other market reads.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlmodel import Session

from stockviz._time import utcnow
from stockviz.db import get_session
from stockviz.limiter import limiter
from stockviz.models import Symbol
from stockviz.schemas import SentimentPointOut, SentimentSeriesOut
from stockviz.services.aegis.read import daily_sentiment
from stockviz.services.metrics import metrics_for

router = APIRouter(prefix="/v1/symbols", tags=["sentiment"])

SessionDep = Annotated[Session, Depends(get_session)]

MAX_DAYS = 365


@router.get("/{ticker}/sentiment", response_model=SentimentSeriesOut)
@limiter.limit("60/minute")
def get_symbol_sentiment(
    request: Request,
    ticker: str,
    session: SessionDep,
    days: Annotated[int, Query(ge=1, le=MAX_DAYS)] = 90,
) -> SentimentSeriesOut:
    """Daily mean Aegis sentiment for ``ticker`` over the trailing ``days``.

    Days with no scored documents are absent rather than emitted as zero — a
    gap and a genuinely neutral day are different readings.
    """
    ticker = ticker.upper()
    if session.get(Symbol, ticker) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Symbol {ticker!r} not found")

    now = utcnow()
    points = [
        SentimentPointOut(date=day, mean_score=mean, article_count=count)
        for day, mean, count in daily_sentiment(
            session, ticker, since=now - timedelta(days=days), until=now
        )
    ]
    metrics = metrics_for(session, ticker)
    return SentimentSeriesOut(
        ticker=ticker,
        points=points,
        rolling_7d=metrics.sentiment_7d if metrics else None,
        rolling_7d_article_count=metrics.sentiment_article_count if metrics else 0,
    )
