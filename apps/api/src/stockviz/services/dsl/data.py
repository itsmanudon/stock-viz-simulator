"""What a rule reads for one symbol, and loading it from the database (A2.1).

:class:`SymbolData` is pure and in memory: the daily bars (with
``delivery_pct`` / ``deliverable_qty`` columns), the venue's benchmark
closes, fundamentals and news. ``cut(t)`` keeps only what was known at bar
``t``: bars dated on or before it, facts with ``available_at`` on or before
its date, news available by its session close. Point mode evaluates on that
cut, so it cannot look ahead.

:func:`load_symbol` fills one from the database, by instrument (never by
ticker column): enough daily bars before ``start`` for the rule's lookback
(the whole history when the lookback is unbounded), and only the bindings
the rule uses.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
from functools import lru_cache

import numpy as np
import pandas as pd
from sqlalchemy import func
from sqlmodel import Session, col, select

from stockviz.services.bars.resample import bar_date
from stockviz.services.dsl.pit import Fact, Fundamentals, News, NewsDoc, to_ns
from stockviz.services.markets.calendar import (
    COMPLETE_AFTER_CLOSE,
    is_session,
    session_complete_at,
    venue_for_ticker,
    venue_zone,
)

BAR_COLUMNS = ["open", "high", "low", "close", "volume", "delivery_pct", "deliverable_qty"]
DELIVERY_SERIES_ORDER = ("EQ", "BE", "BZ", "SM", "ST")
"""When ``eod_extras`` holds several series for a session, the first here wins."""


@lru_cache(maxsize=200_000)
def session_close_ns(day: date, venue: str) -> int:
    """When ``day``'s session closed on ``venue`` (UTC epoch ns). A day the
    calendar does not list closes at the end of the venue's day."""
    if is_session(day, venue):
        return to_ns(session_complete_at(day, venue) - COMPLETE_AFTER_CLOSE)
    return to_ns(datetime.combine(day + timedelta(days=1), time.min, tzinfo=venue_zone(venue)))


@dataclass(frozen=True)
class SymbolData:
    ticker: str
    venue: str
    bars: pd.DataFrame
    """Daily bars indexed by venue date (DatetimeIndex, oldest first), float
    columns ``BAR_COLUMNS``; delivery columns NaN where there is no data."""
    benchmark: pd.Series | None = None
    """The venue index's daily closes by date, or None."""
    benchmark_ticker: str | None = None
    fundamentals: Fundamentals | None = None
    news: News | None = None
    delivery_loaded: bool = False
    """Whether ``eod_extras`` held any row for this instrument."""

    @property
    def dates(self) -> list[date]:
        return [ts.date() for ts in self.bars.index]

    def cut(self, day: date) -> SymbolData:
        """What was known at bar ``day``'s close."""
        end = pd.Timestamp(day)
        cutoff = session_close_ns(day, self.venue)
        return replace(
            self,
            bars=self.bars.loc[:end],
            benchmark=self.benchmark.loc[:end] if self.benchmark is not None else None,
            fundamentals=self.fundamentals.cut(day) if self.fundamentals is not None else None,
            news=self.news.cut(cutoff) if self.news is not None else None,
        )

    def cutoffs(self) -> np.ndarray:
        """Each bar's session close, UTC epoch ns (the news cutoff)."""
        return np.array([session_close_ns(d, self.venue) for d in self.dates], dtype=np.int64)


def bars_frame(rows: list[tuple]) -> pd.DataFrame:
    """``(date, open, high, low, close, volume)`` rows -> a bar frame."""
    index = pd.DatetimeIndex([pd.Timestamp(r[0]) for r in rows])
    data = {
        name: np.array([float(r[i]) for r in rows], dtype=float)
        for i, name in enumerate(("open", "high", "low", "close", "volume"), start=1)
    }
    frame = pd.DataFrame(data, index=index)
    frame["delivery_pct"] = np.nan
    frame["deliverable_qty"] = np.nan
    return frame


# --- loading ----------------------------------------------------------------


@dataclass(frozen=True)
class Needs:
    benchmark: bool = False
    fundamentals: bool = False
    news: bool = False
    delivery: bool = False


def _daily_rows(
    session: Session,
    ticker: str,
    venue: str,
    *,
    start: date | None,
    end: date,
    lookback: int | None,
) -> list[tuple]:
    from stockviz.models import PriceBar
    from stockviz.services.instruments import instrument_of

    upper = datetime.combine(end + timedelta(days=1), time.min)
    base = select(PriceBar).where(
        PriceBar.instrument_id == instrument_of(ticker),
        PriceBar.interval == "1d",
        col(PriceBar.ts) < upper,
    )
    if lookback is None or start is None:
        rows = list(session.exec(base.order_by(col(PriceBar.ts))).all())
    else:
        lower = datetime.combine(start, time.min)
        window = list(
            session.exec(base.where(col(PriceBar.ts) >= lower).order_by(col(PriceBar.ts))).all()
        )
        # No bar in the window (``start`` after the newest stored bar): the
        # newest bar before it is the window, so it still gets its warm-up.
        warm = list(
            session.exec(
                base.where(col(PriceBar.ts) < lower)
                .order_by(col(PriceBar.ts).desc())
                .limit(lookback + (0 if window else 1))
            ).all()
        )
        warm.reverse()
        rows = warm + window
    return [(bar_date(r.ts, venue), r.open, r.high, r.low, r.close, r.volume) for r in rows]


def _delivery(session: Session, instrument_id: int, first: date, end: date) -> tuple[dict, bool]:
    from stockviz.models.eod import EodExtras

    any_row = session.exec(
        select(col(EodExtras.session_date)).where(EodExtras.instrument_id == instrument_id).limit(1)
    ).first()
    rows = session.exec(
        select(EodExtras).where(
            EodExtras.instrument_id == instrument_id,
            col(EodExtras.session_date) >= first,
            col(EodExtras.session_date) <= end,
        )
    ).all()
    rank = {s: i for i, s in enumerate(DELIVERY_SERIES_ORDER)}
    chosen: dict[date, object] = {}
    for row in sorted(rows, key=lambda r: (rank.get(r.series, 99), r.series), reverse=True):
        chosen[row.session_date] = row
    return chosen, any_row is not None


def _fundamentals(
    session: Session, ticker: str, instrument_id: int | None, end: date
) -> Fundamentals:
    from stockviz.models import FxRate, Symbol
    from stockviz.models.fundamentals import FundamentalFact

    symbol = session.get(Symbol, ticker)
    trading = (symbol.currency if symbol else None) or "USD"
    facts: list[Fact] = []
    if instrument_id is not None:
        for row in session.exec(
            select(FundamentalFact).where(
                FundamentalFact.instrument_id == instrument_id,
                col(FundamentalFact.available_at) <= end,
            )
        ).all():
            facts.append(
                Fact(row.concept, row.period_type, row.period_end, row.value, row.available_at,
                     row.source, row.currency, row.point_in_time)
            )  # fmt: skip
    currencies = {trading} | {f.currency for f in facts if f.currency}
    fx: dict = {}
    for currency in currencies - {"USD"}:
        rates = session.exec(
            select(col(FxRate.date), col(FxRate.usd_rate))
            .where(FxRate.currency == currency, col(FxRate.date) <= end)
            .order_by(col(FxRate.date))
        ).all()
        fx[currency] = tuple((d, r) for d, r in rates)
    return Fundamentals(tuple(facts), trading, fx)


def _news(session: Session, ticker: str, since: datetime, cutoff: datetime) -> News:
    from stockviz.models import AegisAnalysis, AegisDocument, AegisEvent
    from stockviz.services.aegis.read import documents_for_ticker

    start = session.exec(select(func.min(AegisDocument.available_at))).first()
    documents = [
        d
        for d in documents_for_ticker(session, ticker, as_of=cutoff, limit=100_000)
        if to_ns(d.available_at) > to_ns(since)
    ]
    ids = [d.document_id for d in documents]
    sentiments: dict[str, list] = {}
    events: dict[str, list] = {}
    if ids:
        for a in session.exec(
            select(AegisAnalysis).where(
                col(AegisAnalysis.document_id).in_(ids), AegisAnalysis.analysis_type == "sentiment"
            )
        ).all():
            sentiments.setdefault(a.document_id, []).append((to_ns(a.available_at), a.label))
        for e in session.exec(select(AegisEvent).where(col(AegisEvent.document_id).in_(ids))).all():
            if e.event_type:
                events.setdefault(e.document_id, []).append(
                    (to_ns(e.available_at), e.event_type.lower())
                )
    docs = tuple(
        NewsDoc(
            to_ns(d.available_at),
            tuple(sorted(sentiments.get(d.document_id, []), key=lambda s: s[0])),
            tuple(sorted(events.get(d.document_id, []))),
        )
        for d in documents
    )
    return News(docs, to_ns(start) if start is not None else None)


def load_symbol(
    session: Session,
    ticker: str,
    *,
    end: date,
    start: date | None = None,
    lookback: int | None = None,
    needs: Needs = Needs(),  # noqa: B008
) -> SymbolData:
    """A symbol's data up to ``end``: bars from ``start`` plus ``lookback``
    bars before it (all history when either is None)."""
    from stockviz.services.event_study import benchmark_for
    from stockviz.services.instruments import instrument_ids

    ticker = ticker.upper()
    venue = venue_for_ticker(ticker)
    rows = _daily_rows(session, ticker, venue, start=start, end=end, lookback=lookback)
    bars = bars_frame(rows)
    data = SymbolData(ticker, venue, bars)
    instrument_id = instrument_ids(session, [ticker]).get(ticker)
    first = rows[0][0] if rows else end

    if needs.delivery and instrument_id is not None:
        chosen, loaded = _delivery(session, instrument_id, first, end)
        for day, row in chosen.items():
            ts = pd.Timestamp(day)
            if ts in bars.index:
                bars.loc[ts, "delivery_pct"] = (
                    float(row.delivery_pct) if row.delivery_pct is not None else np.nan  # type: ignore[attr-defined]
                )
                bars.loc[ts, "deliverable_qty"] = (
                    float(row.deliverable_qty) if row.deliverable_qty is not None else np.nan  # type: ignore[attr-defined]
                )
        data = replace(data, delivery_loaded=loaded)

    if needs.benchmark:
        bench_ticker = benchmark_for(ticker)
        if bench_ticker is not None:
            bench_rows = _daily_rows(
                session, bench_ticker, venue_for_ticker(bench_ticker),
                start=first - timedelta(days=10), end=end, lookback=0,
            )  # fmt: skip
            bench = pd.Series(
                [float(r[4]) for r in bench_rows],
                index=pd.DatetimeIndex([pd.Timestamp(r[0]) for r in bench_rows]),
                dtype=float,
            )
            data = replace(data, benchmark=bench, benchmark_ticker=bench_ticker)

    if needs.fundamentals:
        data = replace(data, fundamentals=_fundamentals(session, ticker, instrument_id, end))

    if needs.news:
        cutoff = datetime.fromtimestamp(session_close_ns(end, venue) / 1e9, UTC)
        since = datetime.combine(first - timedelta(days=400), time.min, tzinfo=UTC)
        data = replace(data, news=_news(session, ticker, since, cutoff))
    return data


__all__ = ["BAR_COLUMNS", "Needs", "SymbolData", "bars_frame", "load_symbol", "session_close_ns"]
