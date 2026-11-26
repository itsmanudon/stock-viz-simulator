"""The news page's archive reads (news redesign, 26 Nov 2026).

``/v1/news`` returns the newest 100 headlines and nothing else, so most of the
copied archive could not be reached. These reads add what the page needs over
the same ``aegis_*`` tables, still headline, source, dates, links, tickers and
Aegis's labels only (no article text exists to read):

- ``feed``: every filter the page offers, keyset paging through the whole
  archive (newest-available first, ``available_at`` then ``document_id``), a
  total, and for each linked ticker the move of the session that followed the
  headline.
- ``overview``: per UTC day of ``available_at`` the count by sentiment (the
  timeline), the filter options with counts, and a coverage heatmap (the most
  covered tickers over the last 30 days of the archive, each day's count and
  net tone).

Dates are the UTC date of ``available_at``, the same as the chart's news
clusters (``symbol_events``) and ``/news``. Never ``published_at`` (AG-12).
"""

from __future__ import annotations

import base64
import binascii
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Literal

from sqlalchemy import func, or_, true
from sqlmodel import Session, col, select

from stockviz.models import (
    AegisAnalysis,
    AegisDocument,
    AegisDocumentEntity,
    AegisMapping,
    PriceBar,
)
from stockviz.services.aegis.read import (
    STOCKVIZ_SCHEME,
    NewsItem,
    _latest_analyses,
    _tickers_by_document,
    stockviz_identifier,
)
from stockviz.services.instruments import instrument_of
from stockviz.services.markets.calendar import (
    COMPLETE_AFTER_CLOSE,
    session_complete_at,
    venue_for_ticker,
)

SENTIMENTS = ("positive", "neutral", "negative", "mixed")
UNSCORED = "unscored"
"""Filter value for documents with no sentiment analysis."""

Scope = Literal["symbols", "market", "all"]

MAX_QUERY_WORDS = 8
HEATMAP_DAYS = 30
HEATMAP_ROWS = 12
FACET_LIMIT = 15
REACTION_TICKERS = 3
"""Tickers per headline that get a price move (the page shows up to three)."""
REACTION_BARS = 5
"""Closes before and after the reaction session in each sparkline."""


@dataclass(frozen=True, slots=True)
class FeedFilters:
    q: str | None = None
    tickers: tuple[str, ...] = ()
    sentiments: tuple[str, ...] = ()
    topics: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()
    scope: Scope = "symbols"
    since: date | None = None
    until: date | None = None


@dataclass(frozen=True, slots=True)
class Reaction:
    """What a linked stock did on the session after the headline.

    Association, not cause: other news and the market moved it too.
    """

    ticker: str
    session_date: date
    change_pct: float | None
    closes: list[float]
    reaction_index: int
    """Position of the reaction session in ``closes``."""


@dataclass(slots=True)
class FeedPage:
    items: list[NewsItem]
    reactions: dict[str, list[Reaction]]
    next_cursor: str | None
    total: int


@dataclass(slots=True)
class Overview:
    total: int
    days: list[dict[str, object]] = field(default_factory=list)
    sentiments: dict[str, int] = field(default_factory=dict)
    topics: list[tuple[str, int]] = field(default_factory=list)
    sources: list[tuple[str, int]] = field(default_factory=list)
    heatmap_days: list[date] = field(default_factory=list)
    heatmap_rows: list[dict[str, object]] = field(default_factory=list)
    first_date: date | None = None
    last_date: date | None = None


class CursorError(ValueError):
    """A cursor this API did not write."""


def encode_cursor(available_at: datetime, document_id: str) -> str:
    raw = f"{available_at.isoformat()}|{document_id}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, str]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        text = base64.urlsafe_b64decode(padded.encode()).decode()
        stamp, document_id = text.split("|", 1)
        return datetime.fromisoformat(stamp), document_id
    except (ValueError, UnicodeDecodeError, binascii.Error) as exc:
        raise CursorError("cursor is not one this API returned") from exc


def _linked(tickers: tuple[str, ...] = ()):
    stmt = (
        select(AegisDocumentEntity.document_id)
        .join(AegisMapping, col(AegisMapping.entity_id) == col(AegisDocumentEntity.entity_id))
        .where(AegisMapping.scheme == STOCKVIZ_SCHEME)
    )
    if tickers:
        stmt = stmt.where(
            col(AegisMapping.identifier).in_([stockviz_identifier(t) for t in tickers])
        )
    return stmt


def _labelled(analysis_type: str, labels: tuple[str, ...]):
    return select(AegisAnalysis.document_id).where(
        AegisAnalysis.analysis_type == analysis_type, col(AegisAnalysis.label).in_(labels)
    )


def _conditions(filters: FeedFilters, *, dates: bool = True) -> list:
    """WHERE clauses on ``AegisDocument`` for every filter."""
    where: list = []
    if filters.scope == "symbols":
        where.append(col(AegisDocument.document_id).in_(_linked()))
    elif filters.scope == "market":
        where.append(col(AegisDocument.document_id).not_in(_linked()))
    if filters.tickers:
        where.append(col(AegisDocument.document_id).in_(_linked(filters.tickers)))
    if filters.q:
        for word in filters.q.split()[:MAX_QUERY_WORDS]:
            escaped = word.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")
            where.append(col(AegisDocument.title).ilike(f"%{escaped}%", escape="\\"))
    if filters.sources:
        where.append(col(AegisDocument.source_name).in_(filters.sources))
    if filters.sentiments:
        labels = tuple(s for s in filters.sentiments if s != UNSCORED)
        options = []
        if labels:
            options.append(col(AegisDocument.document_id).in_(_labelled("sentiment", labels)))
        if UNSCORED in filters.sentiments:
            scored = select(AegisAnalysis.document_id).where(
                AegisAnalysis.analysis_type == "sentiment"
            )
            options.append(col(AegisDocument.document_id).not_in(scored))
        where.append(or_(*options))
    if filters.topics:
        where.append(col(AegisDocument.document_id).in_(_labelled("topic", filters.topics)))
    if dates and filters.since is not None:
        where.append(AegisDocument.available_at >= datetime.combine(filters.since, time.min))
    if dates and filters.until is not None:
        end = datetime.combine(filters.until + timedelta(days=1), time.min)
        where.append(AegisDocument.available_at < end)
    return where


def _items(session: Session, documents: list[AegisDocument]) -> list[NewsItem]:
    ids = [d.document_id for d in documents]
    linked = _tickers_by_document(session, ids)
    sentiments = _latest_analyses(session, ids, "sentiment")
    topics = _latest_analyses(session, ids, "topic")
    out = []
    for doc in documents:
        sentiment = sentiments.get(doc.document_id)
        topic = topics.get(doc.document_id)
        out.append(
            NewsItem(
                document=doc,
                tickers=tuple(linked.get(doc.document_id, [])),
                sentiment=sentiment.label if sentiment else None,
                sentiment_model=(
                    f"{sentiment.model_name}@{sentiment.model_version}" if sentiment else None
                ),
                topic=topic.label if topic else None,
            )
        )
    return out


def feed(
    session: Session, filters: FeedFilters, *, cursor: str | None = None, limit: int = 50
) -> FeedPage:
    """One page, newest-available first, and the total for the filters."""
    where = _conditions(filters)
    total = session.exec(
        select(func.count()).select_from(AegisDocument).where(true(), *where)
    ).one()
    stmt = select(AegisDocument).where(true(), *where)
    if cursor:
        at, doc_id = decode_cursor(cursor)
        stmt = stmt.where(
            or_(
                col(AegisDocument.available_at) < at,
                (col(AegisDocument.available_at) == at) & (col(AegisDocument.document_id) > doc_id),
            )
        )
    documents = list(
        session.exec(
            stmt.order_by(
                col(AegisDocument.available_at).desc(), col(AegisDocument.document_id)
            ).limit(limit + 1)
        ).all()
    )
    more = len(documents) > limit
    documents = documents[:limit]
    items = _items(session, documents)
    next_cursor = (
        encode_cursor(documents[-1].available_at, documents[-1].document_id) if more else None
    )
    return FeedPage(items, reactions(session, items), next_cursor, int(total))


# ---------------------------------------------------------------------------
# Price reactions
# ---------------------------------------------------------------------------


def _reaction_index(dates: list[date], available_at: datetime, venue: str) -> int | None:
    """First stored session that closed after ``available_at``: the market could
    not react before. The rule ``event_study`` uses."""
    when = available_at if available_at.tzinfo else available_at.replace(tzinfo=UTC)
    for i, d in enumerate(dates):
        if session_complete_at(d, venue) - COMPLETE_AFTER_CLOSE > when:
            return i
    return None


def reactions(session: Session, items: list[NewsItem]) -> dict[str, list[Reaction]]:
    """Per document id, the reaction of its first linked tickers (up to three).

    One bar query per ticker on the page, bounded to the page's dates.
    """
    wanted: dict[str, list[datetime]] = defaultdict(list)
    for item in items:
        for ticker in item.tickers[:REACTION_TICKERS]:
            wanted[ticker].append(item.document.available_at)
    bars: dict[str, list[tuple[date, float]]] = {}
    for ticker, stamps in wanted.items():
        start = min(stamps) - timedelta(days=REACTION_BARS * 2 + 7)
        end = max(stamps) + timedelta(days=REACTION_BARS * 2 + 7)
        rows = session.exec(
            select(col(PriceBar.ts), col(PriceBar.close))
            .where(
                PriceBar.instrument_id == instrument_of(ticker),
                PriceBar.interval == "1d",
                PriceBar.ts >= start,
                PriceBar.ts <= end,
            )
            .order_by(col(PriceBar.ts))
        ).all()
        bars[ticker] = [(ts.date(), float(close)) for ts, close in rows if close and close > 0]
    out: dict[str, list[Reaction]] = {}
    for item in items:
        found: list[Reaction] = []
        for ticker in item.tickers[:REACTION_TICKERS]:
            series = bars.get(ticker)
            if not series:
                continue
            dates = [d for d, _ in series]
            i = _reaction_index(dates, item.document.available_at, venue_for_ticker(ticker))
            if i is None:
                continue
            closes = [c for _, c in series]
            lo = max(0, i - REACTION_BARS)
            hi = min(len(closes), i + REACTION_BARS + 1)
            change = (closes[i] / closes[i - 1] - 1) * 100 if i > 0 else None
            found.append(
                Reaction(
                    ticker=ticker,
                    session_date=dates[i],
                    change_pct=round(change, 2) if change is not None else None,
                    closes=closes[lo:hi],
                    reaction_index=i - lo,
                )
            )
        if found:
            out[item.document.document_id] = found
    return out


# ---------------------------------------------------------------------------
# Overview: timeline, facets, heatmap
# ---------------------------------------------------------------------------


def overview(session: Session, filters: FeedFilters) -> Overview:
    """Counts over every document the filters match, dates aside.

    The timeline and the heatmap ignore ``since``/``until`` so the page can show
    the whole archive and brush a range on it; the facet counts honour them,
    like the feed.
    """
    all_dates = session.exec(
        select(
            AegisDocument.document_id, AegisDocument.available_at, AegisDocument.source_name
        ).where(true(), *_conditions(filters, dates=False))
    ).all()
    out = Overview(total=0)
    if not all_dates:
        return out
    ids = [row[0] for row in all_dates]
    sentiment_of = {doc: a.label for doc, a in _latest_analyses(session, ids, "sentiment").items()}
    topic_of = {doc: a.label for doc, a in _latest_analyses(session, ids, "topic").items()}

    by_day: dict[date, Counter[str]] = defaultdict(Counter)
    for doc_id, available_at, _source in all_dates:
        label = sentiment_of.get(doc_id)
        by_day[available_at.date()][label if label in SENTIMENTS else UNSCORED] += 1
    out.first_date = min(by_day)
    out.last_date = max(by_day)
    day = out.first_date
    while day <= out.last_date:
        counts = by_day.get(day, Counter())
        out.days.append({"date": day, **{k: counts.get(k, 0) for k in (*SENTIMENTS, UNSCORED)}})
        day += timedelta(days=1)

    in_range = [
        row
        for row in all_dates
        if (filters.since is None or row[1].date() >= filters.since)
        and (filters.until is None or row[1].date() <= filters.until)
    ]
    out.total = len(in_range)
    sentiments = Counter(
        sentiment_of.get(d) if sentiment_of.get(d) in SENTIMENTS else UNSCORED
        for d, _, _ in in_range
    )
    out.sentiments = {k: sentiments.get(k, 0) for k in (*SENTIMENTS, UNSCORED)}
    out.topics = Counter(t for d, _, _ in in_range if (t := topic_of.get(d))).most_common(
        FACET_LIMIT
    )
    out.sources = Counter(s for _, _, s in in_range).most_common(FACET_LIMIT)

    # Heatmap: the archive's last 30 days (filters aside from dates), the most
    # covered tickers in them, each day's count and net tone (+1 positive,
    # -1 negative, 0 neutral, mixed or unscored, over the day's count).
    out.heatmap_days = [out.last_date - timedelta(days=n) for n in range(HEATMAP_DAYS - 1, -1, -1)]
    window_start = out.heatmap_days[0]
    recent = [row for row in all_dates if row[1].date() >= window_start]
    tickers_of = _tickers_by_document(session, [r[0] for r in recent])
    cells: dict[str, dict[date, list[int]]] = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    totals: Counter[str] = Counter()
    for doc_id, available_at, _ in recent:
        tone = {"positive": 1, "negative": -1}.get(sentiment_of.get(doc_id) or "", 0)
        for ticker in tickers_of.get(doc_id, []):
            if filters.tickers and ticker not in filters.tickers:
                continue
            cell = cells[ticker][available_at.date()]
            cell[0] += 1
            cell[1] += tone
            totals[ticker] += 1
    for ticker, total in sorted(totals.items(), key=lambda kv: (-kv[1], kv[0]))[:HEATMAP_ROWS]:
        out.heatmap_rows.append(
            {
                "ticker": ticker,
                "total": total,
                "cells": [
                    {
                        "date": d,
                        "count": cells[ticker][d][0],
                        "net": (
                            round(cells[ticker][d][1] / cells[ticker][d][0], 2)
                            if cells[ticker][d][0]
                            else None
                        ),
                    }
                    for d in out.heatmap_days
                ],
            }
        )
    return out
