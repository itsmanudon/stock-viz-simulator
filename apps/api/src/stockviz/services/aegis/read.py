"""Reads over the copied Aegis tables.

Documents link to StockViz symbols through the local join
document -> resolved entity -> Aegis mapping ``provider_id`` ``stockviz:<ticker>``.
Because the join runs at read time, a mapping seeded after a document was
synced still links it.

Point in time: ``as_of`` bounds on the document's ``available_at``, never on
``published_at`` (audit AG-12).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlmodel import Session, col, select

from stockviz.models import AegisAnalysis, AegisDocument, AegisDocumentEntity, AegisMapping

STOCKVIZ_SCHEME = "provider_id"


def stockviz_identifier(ticker: str) -> str:
    return f"stockviz:{ticker.strip().upper()}"


def documents_for_ticker(
    session: Session, ticker: str, *, as_of: datetime | None = None, limit: int = 50
) -> list[AegisDocument]:
    """Newest-available first. Each document once, however many entities link it."""
    linked = (
        select(AegisDocumentEntity.document_id)
        .join(AegisMapping, col(AegisMapping.entity_id) == col(AegisDocumentEntity.entity_id))
        .where(
            AegisMapping.scheme == STOCKVIZ_SCHEME,
            AegisMapping.identifier == stockviz_identifier(ticker),
        )
    )
    stmt = select(AegisDocument).where(col(AegisDocument.document_id).in_(linked))
    if as_of is not None:
        stmt = stmt.where(AegisDocument.available_at <= as_of)
    stmt = stmt.order_by(
        col(AegisDocument.available_at).desc(), col(AegisDocument.document_id)
    ).limit(limit)
    return list(session.exec(stmt).all())


# ---------------------------------------------------------------------------
# News items and sentiment, for the pages (Phase 2 task 5) and the signals
# vote and screener filter (audits AG-14, SR-9).
# ---------------------------------------------------------------------------

SENTIMENT_WINDOW_DAYS = 7
"""Trailing window for symbol_metrics.sentiment_7d, as before the switch."""


@dataclass(frozen=True, slots=True)
class NewsItem:
    document: AegisDocument
    tickers: tuple[str, ...]
    sentiment: str | None
    sentiment_model: str | None
    topic: str | None


def _tickers_by_document(session: Session, document_ids: list[str]) -> dict[str, list[str]]:
    if not document_ids:
        return {}
    rows = session.exec(
        select(AegisDocumentEntity.document_id, AegisMapping.identifier)
        .join(AegisMapping, col(AegisMapping.entity_id) == col(AegisDocumentEntity.entity_id))
        .where(
            col(AegisDocumentEntity.document_id).in_(document_ids),
            AegisMapping.scheme == STOCKVIZ_SCHEME,
        )
    ).all()
    out: dict[str, list[str]] = {}
    for document_id, identifier in rows:
        ticker = identifier.removeprefix("stockviz:")
        if ticker not in out.setdefault(document_id, []):
            out[document_id].append(ticker)
    return {doc: sorted(tickers) for doc, tickers in out.items()}


def _latest_analyses(
    session: Session, document_ids: list[str], analysis_type: str
) -> dict[str, AegisAnalysis]:
    if not document_ids:
        return {}
    rows = session.exec(
        select(AegisAnalysis)
        .where(
            col(AegisAnalysis.document_id).in_(document_ids),
            AegisAnalysis.analysis_type == analysis_type,
        )
        .order_by(col(AegisAnalysis.available_at))
    ).all()
    # A bundle holds one run, so normally one per type; the newest wins if not.
    return {row.document_id: row for row in rows}


def news_items(session: Session, *, ticker: str | None = None, limit: int = 50) -> list[NewsItem]:
    """Newest-available first: for one ticker, or every linked document.

    ``/v1/news`` lists only documents linked to a StockViz symbol, so the page
    never shows news about companies StockViz does not cover.
    """
    if ticker is not None:
        documents = documents_for_ticker(session, ticker, limit=limit)
    else:
        linked = (
            select(AegisDocumentEntity.document_id)
            .join(AegisMapping, col(AegisMapping.entity_id) == col(AegisDocumentEntity.entity_id))
            .where(AegisMapping.scheme == STOCKVIZ_SCHEME)
        )
        documents = list(
            session.exec(
                select(AegisDocument)
                .where(col(AegisDocument.document_id).in_(linked))
                .order_by(col(AegisDocument.available_at).desc(), col(AegisDocument.document_id))
                .limit(limit)
            ).all()
        )
    ids = [d.document_id for d in documents]
    tickers = _tickers_by_document(session, ids)
    sentiments = _latest_analyses(session, ids, "sentiment")
    topics = _latest_analyses(session, ids, "topic")
    items = []
    for document in documents:
        sentiment = sentiments.get(document.document_id)
        topic = topics.get(document.document_id)
        items.append(
            NewsItem(
                document=document,
                tickers=tuple(tickers.get(document.document_id, [])),
                sentiment=sentiment.label if sentiment else None,
                sentiment_model=(
                    f"{sentiment.model_name}@{sentiment.model_version}" if sentiment else None
                ),
                topic=topic.label if topic else None,
            )
        )
    return items


def _sentiment_scores(
    session: Session, *, since: datetime, until: datetime, ticker: str | None = None
) -> list[tuple[str, datetime, float]]:
    """(ticker, analysis available_at, score) for linked sentiment analyses in a window.

    Bounded on the analysis's own ``available_at`` (point in time), never on
    ``published_at``.
    """
    stmt = (
        select(
            AegisMapping.identifier,
            AegisAnalysis.available_at,
            AegisAnalysis.score,
            AegisAnalysis.analysis_id,
        )
        .join(
            AegisDocumentEntity,
            col(AegisDocumentEntity.document_id) == col(AegisAnalysis.document_id),
        )
        .join(AegisMapping, col(AegisMapping.entity_id) == col(AegisDocumentEntity.entity_id))
        .where(
            AegisAnalysis.analysis_type == "sentiment",
            col(AegisAnalysis.score).is_not(None),
            AegisAnalysis.available_at >= since,
            AegisAnalysis.available_at <= until,
            AegisMapping.scheme == STOCKVIZ_SCHEME,
        )
    )
    if ticker is not None:
        stmt = stmt.where(AegisMapping.identifier == stockviz_identifier(ticker))
    # One score per (ticker, analysis), however many entities link them.
    rows = session.exec(stmt).all()
    unique: dict[tuple[str, str], tuple[str, datetime, float]] = {}
    for identifier, available_at, score, analysis_id in rows:
        ticker_id = identifier.removeprefix("stockviz:")
        if score is not None:
            unique[(ticker_id, analysis_id)] = (ticker_id, available_at, float(score))
    return list(unique.values())


def refresh_aegis_sentiment(
    session: Session,
    *,
    now: datetime,
    window_days: int = SENTIMENT_WINDOW_DAYS,
    commit: bool = True,
) -> int:
    """Write the trailing mean Aegis sentiment onto every active symbol.

    Replaces the legacy aggregate as the producer of ``sentiment_7d``, which
    the signals vote and the screener filter read (audit AG-14). A symbol with
    no scored Aegis document in the window gets NULL: no signal, not neutral.
    """
    from stockviz.models import Symbol
    from stockviz.services.metrics import set_sentiment

    scores: dict[str, list[float]] = {}
    for ticker, _at, score in _sentiment_scores(
        session, since=now - timedelta(days=window_days), until=now
    ):
        scores.setdefault(ticker, []).append(score)

    active = session.exec(select(Symbol.ticker).where(Symbol.is_active)).all()
    for ticker in active:
        values = scores.get(ticker, [])
        set_sentiment(
            session,
            ticker=ticker,
            mean_score=sum(values) / len(values) if values else None,
            article_count=len(values),
            as_of=now.date(),
        )
    if commit:
        session.commit()
    return len(active)


def daily_sentiment(
    session: Session, ticker: str, *, since: datetime, until: datetime
) -> list[tuple[str, float, int]]:
    """(UTC date, mean score, count) per day an analysis became available."""
    by_day: dict[str, list[float]] = {}
    for _ticker, available_at, score in _sentiment_scores(
        session, since=since, until=until, ticker=ticker
    ):
        by_day.setdefault(available_at.date().isoformat(), []).append(score)
    return [(day, sum(v) / len(v), len(v)) for day, v in sorted(by_day.items())]
