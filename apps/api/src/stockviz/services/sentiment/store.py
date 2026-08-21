"""Persisting sentiment scores and rolling them up per symbol.

Three jobs live here:

- :func:`score_articles` — score a set of articles with the configured provider
  and persist the results, deduplicating by URL so a repeated input isn't paid
  for twice.
- :func:`backfill_unscored` — find articles with no score for the current model
  and score them. This is what makes a newly connected provider useful: every
  row ingested while scoring was disabled (in production, that is *all* of
  them, because ANTHROPIC_API_KEY was never set in render.yaml) can be
  processed after the fact.
- :func:`refresh_symbol_sentiment` — roll scores up into the rolling per-ticker
  average on ``symbol_metrics``, which is what the screener filters on and the
  recommendation engine votes with.
"""

from __future__ import annotations

import logging
from datetime import date as date_type
from datetime import timedelta
from decimal import Decimal

from sqlmodel import Session, select

from stockviz._time import utcnow
from stockviz.models import NewsArticle, Symbol
from stockviz.models.sentiment import NewsSentiment
from stockviz.services.metrics import set_sentiment
from stockviz.services.sentiment import get_provider
from stockviz.services.sentiment.base import SentimentInput, SentimentProvider, SentimentScore
from stockviz.settings import Settings, get_settings

logger = logging.getLogger(__name__)

ROLLING_WINDOW_DAYS = 7
"""Trailing window for the per-symbol aggregate the screener filters on."""


def _persist(session: Session, article_id: int, result: SentimentScore) -> None:
    """Upsert one (article, model) score."""
    existing = session.exec(
        select(NewsSentiment).where(
            NewsSentiment.article_id == article_id,
            NewsSentiment.model == result.model,
        )
    ).first()

    if existing is None:
        session.add(
            NewsSentiment(
                article_id=article_id,
                model=result.model,
                label=result.label,
                score=Decimal(str(round(result.score, 4))),
                confidence=(
                    None if result.confidence is None else Decimal(str(round(result.confidence, 4)))
                ),
            )
        )
        return

    existing.label = result.label
    existing.score = Decimal(str(round(result.score, 4)))
    existing.confidence = (
        None if result.confidence is None else Decimal(str(round(result.confidence, 4)))
    )
    existing.scored_at = utcnow()
    session.add(existing)


def score_articles(
    session: Session,
    articles: list[NewsArticle],
    *,
    provider: SentimentProvider | None = None,
    settings: Settings | None = None,
) -> int:
    """Score and persist ``articles``. Returns the number of scores written.

    Inputs are deduplicated by URL before dispatch, so a caller passing
    overlapping batches pays for each story once. (``news_articles.url`` is
    globally unique, so this is about repeated inputs rather than duplicate
    rows.)
    """
    settings = settings or get_settings()
    provider = provider or get_provider(settings)

    scorable = [a for a in articles if a.id is not None]
    if not scorable:
        return 0

    cap = settings.sentiment_daily_document_cap
    if cap and len(scorable) > cap:
        logger.warning(
            "sentiment: %d documents exceeds the cap of %d; scoring the first %d",
            len(scorable),
            cap,
            cap,
        )
        scorable = scorable[:cap]

    # Dedupe on URL, remembering every article id that shares it so they all
    # get the same score written.
    ids_by_url: dict[str, list[int]] = {}
    representative: dict[str, NewsArticle] = {}
    for article in scorable:
        ids_by_url.setdefault(article.url, []).append(article.id)  # type: ignore[arg-type]
        representative.setdefault(article.url, article)

    urls = list(representative)
    inputs = [
        SentimentInput(
            headline=representative[url].title,
            summary=representative[url].summary,
            ticker=representative[url].ticker,
        )
        for url in urls
    ]

    results = provider.score(inputs)
    written = 0
    for url, result in zip(urls, results, strict=True):
        if result is None:
            continue
        for article_id in ids_by_url[url]:
            _persist(session, article_id, result)
            written += 1
        # Keep the denormalized badge column in step with the newest score.
        for article in scorable:
            if article.url == url:
                article.sentiment = result.label
                session.add(article)

    session.commit()
    logger.info(
        "sentiment: scored %d/%d documents with %s",
        sum(1 for r in results if r is not None),
        len(urls),
        getattr(provider, "name", "unknown"),
    )
    return written


def backfill_unscored(
    session: Session,
    *,
    since: date_type | None = None,
    limit: int | None = None,
    provider: SentimentProvider | None = None,
    settings: Settings | None = None,
) -> int:
    """Score articles that have no result yet for the active model.

    Without this, rows ingested while scoring was off stay NULL forever — and
    in production that was every row, because ANTHROPIC_API_KEY was missing
    from the Render blueprint.
    """
    settings = settings or get_settings()
    provider = provider or get_provider(settings)
    model = getattr(provider, "name", "")
    if model in ("", "none"):
        logger.info("sentiment: no provider configured; nothing to backfill")
        return 0

    scored_ids = select(NewsSentiment.article_id).where(NewsSentiment.model == model)
    stmt = select(NewsArticle).where(NewsArticle.id.not_in(scored_ids))  # type: ignore[attr-defined]
    if since is not None:
        stmt = stmt.where(NewsArticle.published_at >= since)
    stmt = stmt.order_by(NewsArticle.published_at.desc())  # type: ignore[attr-defined]
    if limit is not None:
        stmt = stmt.limit(limit)

    articles = list(session.exec(stmt).all())
    if not articles:
        return 0
    return score_articles(session, articles, provider=provider, settings=settings)


def refresh_symbol_sentiment(
    session: Session,
    *,
    model: str | None = None,
    window_days: int = ROLLING_WINDOW_DAYS,
    asof: date_type | None = None,
) -> int:
    """Recompute the trailing mean sentiment per symbol onto ``symbol_metrics``.

    Uses the newest score per article for the given model. Symbols with no
    scored articles in the window get NULL rather than 0 — "no signal" and
    "neutral signal" are different things, and the screener must not treat
    silence as a neutral reading.
    """
    asof = asof or utcnow().date()
    cutoff = asof - timedelta(days=window_days)

    stmt = (
        select(NewsArticle.ticker, NewsSentiment.score)  # type: ignore[call-overload]
        .join(NewsSentiment, NewsSentiment.article_id == NewsArticle.id)  # type: ignore[arg-type]
        .where(
            NewsArticle.ticker.is_not(None),  # type: ignore[union-attr]
            NewsArticle.published_at >= cutoff,
        )
    )
    if model:
        stmt = stmt.where(NewsSentiment.model == model)

    scores_by_ticker: dict[str, list[Decimal]] = {}
    for ticker, score in session.exec(stmt).all():
        if ticker:
            scores_by_ticker.setdefault(ticker, []).append(score)

    tickers = list(session.exec(select(Symbol.ticker).where(Symbol.is_active)).all())
    updated = 0
    for ticker in tickers:
        scores = scores_by_ticker.get(ticker, [])
        mean = float(sum(scores) / len(scores)) if scores else None
        set_sentiment(
            session,
            ticker=ticker,
            mean_score=mean,
            article_count=len(scores),
            as_of=asof,
        )
        updated += 1

    session.commit()
    logger.info(
        "sentiment: refreshed rolling aggregate for %d symbols (%d with signal)",
        updated,
        sum(1 for t in tickers if scores_by_ticker.get(t)),
    )
    return updated
