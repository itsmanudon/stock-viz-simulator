"""`/v1/symbols/{ticker}/sentiment` — daily mean news sentiment.

Until now sentiment existed only as a badge next to a headline. This exposes it
as a time series so the ticker page can overlay news mood on the price chart,
which is the question the data was collected to answer: does the mood track the
move?

Public and rate-limited like the other market reads.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func
from sqlmodel import Session, select

from stockviz._time import utcnow
from stockviz.db import get_session
from stockviz.limiter import limiter
from stockviz.models import NewsArticle, Symbol, SymbolMetrics
from stockviz.models.sentiment import NewsSentiment
from stockviz.schemas import SentimentPointOut, SentimentSeriesOut

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
    model: Annotated[str | None, Query()] = None,
) -> SentimentSeriesOut:
    """Daily mean sentiment for ``ticker`` over the trailing ``days``.

    Days with no scored articles are simply absent from the series rather than
    emitted as zero — a gap and a genuinely neutral day are different readings,
    and a chart should not draw them the same way.
    """
    ticker = ticker.upper()
    if session.get(Symbol, ticker) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Symbol {ticker!r} not found")

    cutoff = utcnow() - timedelta(days=days)
    day = func.date(NewsArticle.published_at).label("day")

    stmt = (
        select(
            day,
            func.avg(NewsSentiment.score).label("mean_score"),
            func.count().label("n"),
        )
        .join(NewsSentiment, NewsSentiment.article_id == NewsArticle.id)  # type: ignore[arg-type]
        .where(NewsArticle.ticker == ticker, NewsArticle.published_at >= cutoff)
    )
    if model:
        stmt = stmt.where(NewsSentiment.model == model)
    stmt = stmt.group_by(day).order_by(day)

    points = [
        SentimentPointOut(date=str(row_day), mean_score=float(mean), article_count=int(n))
        for row_day, mean, n in session.exec(stmt).all()  # type: ignore[misc]
    ]

    metrics = session.get(SymbolMetrics, ticker)
    return SentimentSeriesOut(
        ticker=ticker,
        points=points,
        rolling_7d=metrics.sentiment_7d if metrics else None,
        rolling_7d_article_count=metrics.sentiment_article_count if metrics else 0,
    )
