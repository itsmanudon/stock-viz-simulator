"""News ingest (newsdata.io).

The free tier returns the 10 latest articles per query. We query per ticker by
company name and dedupe on ``url`` via the unique constraint.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from stockviz.models import NewsArticle

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ArticleRecord:
    ticker: str | None
    title: str
    url: str
    source: str | None
    published_at: datetime
    summary: str | None
    image_url: str | None
    sentiment: str | None = None


NewsdataFetchFn = Callable[[str, str], dict[str, Any]]
"""(api_key, query) -> raw JSON dict."""


def _default_newsdata_fetch(api_key: str, query: str) -> dict[str, Any]:
    response = httpx.get(
        "https://newsdata.io/api/1/latest",
        params={"apikey": api_key, "qInTitle": query, "language": "en"},
        timeout=30.0,
    )
    response.raise_for_status()
    return response.json()


def _parse_published_at(value: str | None) -> datetime | None:
    if not value:
        return None
    # newsdata.io: "2025-04-13 07:17:01"
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    logger.warning("news: unrecognized pubDate format: %r", value)
    return None


def fetch_newsdata(
    *,
    api_key: str,
    query: str,
    ticker: str | None = None,
    fetch_fn: NewsdataFetchFn = _default_newsdata_fetch,
) -> list[ArticleRecord]:
    """Return parsed articles for a single newsdata.io query.

    ``ticker`` is informational — it gets stamped onto each article so the
    write side knows which symbol the query was for.
    """

    if not api_key:
        return []

    payload = fetch_fn(api_key, query)
    results = payload.get("results") or []

    articles: list[ArticleRecord] = []
    for item in results:
        url = item.get("link") or item.get("url")
        title = item.get("title")
        published = _parse_published_at(item.get("pubDate"))
        if not url or not title or published is None:
            continue
        articles.append(
            ArticleRecord(
                ticker=ticker,
                title=title,
                url=url,
                source=item.get("source_id") or item.get("source_name"),
                published_at=published,
                summary=item.get("description"),
                image_url=item.get("image_url") or None,
            )
        )
    return articles


def insert_new_articles(session: Session, articles: list[ArticleRecord]) -> list[NewsArticle]:
    """Insert genuinely new articles. Does not commit.

    On PostgreSQL uses ``ON CONFLICT DO NOTHING RETURNING``. SQLite walks
    rows and skips unique-url collisions. Duplicate URLs never produce a
    second row.
    """

    if not articles:
        return []

    rows = [
        {
            "ticker": a.ticker,
            "title": a.title,
            "url": a.url,
            "source": a.source,
            "published_at": a.published_at,
            "summary": a.summary,
            "image_url": a.image_url,
            "sentiment": a.sentiment,
        }
        for a in articles
    ]

    bind = session.get_bind()
    dialect = bind.dialect.name if bind is not None else "sqlite"
    if dialect == "postgresql":
        stmt = (
            pg_insert(NewsArticle)
            .values(rows)
            .on_conflict_do_nothing(index_elements=["url"])
            .returning(col(NewsArticle.id))
        )
        result = session.exec(stmt)  # type: ignore[arg-type]
        ids = [row[0] if not isinstance(row, int) else row for row in result.all()]
        if not ids:
            return []
        stored = list(session.exec(select(NewsArticle).where(NewsArticle.id.in_(ids))).all())  # type: ignore[attr-defined]
        return stored

    inserted: list[NewsArticle] = []
    for row in rows:
        existing = session.exec(select(NewsArticle).where(NewsArticle.url == row["url"])).first()
        if existing is not None:
            continue
        article = NewsArticle(**row)
        try:
            with session.begin_nested():
                session.add(article)
                session.flush()
        except IntegrityError:
            continue
        inserted.append(article)
    return inserted


def upsert_articles(session: Session, articles: list[ArticleRecord]) -> int:
    """Insert new articles and commit. Returns the number **actually inserted**."""
    inserted = insert_new_articles(session, articles)
    session.commit()
    return len(inserted)


def ingest_news_for_ticker(
    session: Session,
    *,
    ticker: str,
    company_name: str,
    newsdata_key: str,
    score_sentiment: bool = False,
) -> int:
    """Fetch and store news for one ticker. Does **not** score sentiment.

    ``score_sentiment`` is ignored; scoring belongs to the news-sentiment
    worker (or ``score-sentiment`` CLI). Kept as a keyword so older callers
    do not break.
    """
    if score_sentiment:
        logger.info("ingest_news_for_ticker: score_sentiment is ignored; scoring is async")
    articles = fetch_newsdata(api_key=newsdata_key, query=company_name, ticker=ticker)
    inserted = insert_new_articles(session, articles)
    session.commit()
    return len(inserted)
