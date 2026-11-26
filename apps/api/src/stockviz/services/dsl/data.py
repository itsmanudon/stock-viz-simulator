"""What a rule reads for one symbol, and loading it from the database (A2.1).

:class:`SymbolData` is pure and in memory: the daily bars (with
``delivery_pct`` / ``deliverable_qty`` columns), the venue's benchmark
closes, fundamentals and news. ``cut(t)`` keeps only what was known at bar
``t``: bars dated on or before it, facts with ``available_at`` on or before
its date, news available by its session close. Point mode evaluates on that
cut, so it cannot look ahead.

**Intraday (A6.4).** On an intraday timeframe (``1m`` ... ``60m``) the bars
are indexed by each bar's **open instant** (naive UTC, as ``intraday_bars``
stores it), and ``closed_at`` holds each bar's close instant, which is when
it became known. ``cut(t)`` keeps the bars opening at or before ``t``, news
available by bar ``t``'s close, facts dated before ``t``'s session (a
date-stamped filing is not known at a given minute of its own day), and the
daily bars of sessions **strictly before** ``t``'s session, so ``daily.``
can never read today's daily bar. :func:`load_symbol_intraday` fills one
from ``intraday_bars`` through ``services/bars/intraday.py`` (closed bars
only).

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
from stockviz.services.dsl.drawings import DrawingRef, Drawings
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


DAILY = "daily"
"""The daily timeframe's name on a setup version (``1d``)."""


@dataclass(frozen=True)
class SymbolData:
    ticker: str
    venue: str
    bars: pd.DataFrame
    """Daily bars indexed by venue date (DatetimeIndex, oldest first), float
    columns ``BAR_COLUMNS``; delivery columns NaN where there is no data.
    Intraday: the timeframe's bars indexed by open instant (naive UTC)."""
    benchmark: pd.Series | None = None
    """The venue index's daily closes by date, or None."""
    benchmark_ticker: str | None = None
    fundamentals: Fundamentals | None = None
    news: News | None = None
    delivery_loaded: bool = False
    """Whether ``eod_extras`` held any row for this instrument."""
    drawings: Drawings | None = None
    """A3.3: the rule owner's drawings on this symbol; None without an owner.
    Kept whole by ``cut``: a drawing is geometry, and its values on a bar
    read only its anchors and bars up to that bar."""
    timeframe: str = DAILY
    """A6.4: ``daily``, or an intraday interval (``1m`` ... ``60m``)."""
    closed_at: np.ndarray | None = None
    """Intraday: each bar's close instant (UTC epoch ns), when it became known."""
    sessions: np.ndarray | None = None
    """Intraday: each bar's venue session date (``datetime64[D]``)."""
    daily: pd.DataFrame | None = None
    """Intraday: the daily bars ``daily.`` / ``weekly.`` / ``monthly.`` read
    (a daily bar frame), or None when the rule reads none."""
    feed: str | None = None
    """Intraday: the stored feed the bars came from (``iex``, ``sip``, ``file`` ...)."""

    @property
    def intraday(self) -> bool:
        return self.timeframe != DAILY

    @property
    def dates(self) -> list[date]:
        """Each bar's date: the session date on intraday timeframes."""
        if self.intraday:
            assert self.sessions is not None
            return [d.item() for d in self.sessions]
        return [ts.date() for ts in self.bars.index]

    @property
    def instants(self) -> list[datetime]:
        """Intraday: each bar's open instant (naive UTC)."""
        return [ts.to_pydatetime() for ts in self.bars.index]

    def cut(self, day: date) -> SymbolData:
        """What was known at bar ``day``'s close (intraday: ``day`` is the
        bar's open instant)."""
        if self.intraday:
            return self._cut_intraday(day)
        end = pd.Timestamp(day)
        cutoff = session_close_ns(day, self.venue)
        return replace(
            self,
            bars=self.bars.loc[:end],
            benchmark=self.benchmark.loc[:end] if self.benchmark is not None else None,
            fundamentals=self.fundamentals.cut(day) if self.fundamentals is not None else None,
            news=self.news.cut(cutoff) if self.news is not None else None,
        )

    def _cut_intraday(self, when: date) -> SymbolData:
        assert self.closed_at is not None and self.sessions is not None
        end = instant(when)
        n = int(self.bars.index.searchsorted(end.to_datetime64(), side="right"))
        if n == 0:
            return replace(self, bars=self.bars.iloc[:0], closed_at=self.closed_at[:0],
                           sessions=self.sessions[:0])  # fmt: skip
        today = self.sessions[n - 1]
        day_before: date = today.item() - timedelta(days=1)
        before = pd.Timestamp(day_before)
        known = int(self.closed_at[n - 1])
        return replace(
            self,
            bars=self.bars.iloc[:n],
            closed_at=self.closed_at[:n],
            sessions=self.sessions[:n],
            daily=self.daily.loc[:before] if self.daily is not None else None,
            benchmark=self.benchmark.loc[:before] if self.benchmark is not None else None,
            fundamentals=(
                self.fundamentals.cut(day_before) if self.fundamentals is not None else None
            ),
            news=self.news.cut(known) if self.news is not None else None,
        )

    def cutoffs(self) -> np.ndarray:
        """Each bar's session close, UTC epoch ns (the news cutoff). Intraday:
        each bar's own close."""
        if self.intraday:
            assert self.closed_at is not None
            return np.asarray(self.closed_at, dtype=np.int64)
        return np.array([session_close_ns(d, self.venue) for d in self.dates], dtype=np.int64)


def instant(when: date | datetime | pd.Timestamp) -> pd.Timestamp:
    """A bar instant as the intraday index holds it: naive UTC."""
    ts = pd.Timestamp(when)
    if ts.tzinfo is not None:
        ts = ts.tz_convert("UTC").tz_localize(None)
    return ts  # pyright: ignore[reportReturnType]


def intraday_frame(bars: list) -> tuple[pd.DataFrame, np.ndarray, np.ndarray]:
    """``services/bars/intraday.IntradayOut`` bars -> (bar frame indexed by
    open instant, close instants in ns, session dates)."""
    index = pd.DatetimeIndex([pd.Timestamp(b.ts) for b in bars])
    frame = pd.DataFrame(
        {
            name: np.array([float(getattr(b, name)) for b in bars], dtype=float)
            for name in ("open", "high", "low", "close", "volume")
        },
        index=index,
    )
    frame["delivery_pct"] = np.nan
    frame["deliverable_qty"] = np.nan
    closed = np.array([to_ns(b.closed_at.replace(tzinfo=UTC)) for b in bars], dtype=np.int64)
    sessions = np.array([np.datetime64(b.session_date, "D") for b in bars], dtype="datetime64[D]")
    return frame, closed, sessions


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
    drawings: bool = False
    """A3.3: the rule reads the owner's drawings (user-scoped)."""
    daily: bool = False
    """A6.4: an intraday rule reads daily bars (``daily.``, ``weekly.``, ``monthly.``)."""


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


def load_drawings(session: Session, user_id: int, instrument_id: int) -> Drawings:
    """The user's drawings on one instrument (A3.3), for ``drawing()`` / ``avwap()``."""
    from stockviz.models.drawing import Drawing

    rows = session.exec(
        select(Drawing)
        .where(col(Drawing.user_id) == user_id, col(Drawing.instrument_id) == instrument_id)
        .order_by(col(Drawing.id))
    ).all()
    items = []
    for row in rows:
        assert row.id is not None
        points = tuple(
            (
                date.fromisoformat(p["ts"]) if p.get("ts") else None,
                float(p["price"]) if p.get("price") is not None else None,
            )
            for p in row.points
        )
        items.append(DrawingRef(row.id, row.kind, row.label, points))
    return Drawings(user_id, tuple(items))


def _fill_delivery(
    session: Session, instrument_id: int, bars: pd.DataFrame, first: date, end: date
) -> bool:
    """Write ``eod_extras`` delivery into daily ``bars`` in place; whether the
    instrument has any delivery row at all."""
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
    return loaded


def _benchmark(session: Session, bench_ticker: str, first: date, end: date) -> pd.Series:
    bench_rows = _daily_rows(
        session, bench_ticker, venue_for_ticker(bench_ticker),
        start=first - timedelta(days=10), end=end, lookback=0,
    )  # fmt: skip
    return pd.Series(
        [float(r[4]) for r in bench_rows],
        index=pd.DatetimeIndex([pd.Timestamp(r[0]) for r in bench_rows]),
        dtype=float,
    )


def load_symbol(
    session: Session,
    ticker: str,
    *,
    end: date,
    start: date | None = None,
    lookback: int | None = None,
    needs: Needs = Needs(),  # noqa: B008
    user_id: int | None = None,
) -> SymbolData:
    """A symbol's data up to ``end``: bars from ``start`` plus ``lookback``
    bars before it (all history when either is None). ``user_id`` is the
    rule's owner: a rule that reads drawings (A3.3) sees that user's, and
    without one its drawing values are unknown."""
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
        data = replace(
            data, delivery_loaded=_fill_delivery(session, instrument_id, bars, first, end)
        )

    if needs.benchmark:
        bench_ticker = benchmark_for(ticker)
        if bench_ticker is not None:
            bench = _benchmark(session, bench_ticker, first, end)
            data = replace(data, benchmark=bench, benchmark_ticker=bench_ticker)

    if needs.fundamentals:
        data = replace(data, fundamentals=_fundamentals(session, ticker, instrument_id, end))

    if needs.drawings and user_id is not None:
        data = replace(
            data,
            drawings=load_drawings(session, user_id, instrument_id)
            if instrument_id is not None
            else Drawings(user_id),
        )

    if needs.news:
        cutoff = datetime.fromtimestamp(session_close_ns(end, venue) / 1e9, UTC)
        since = datetime.combine(first - timedelta(days=400), time.min, tzinfo=UTC)
        data = replace(data, news=_news(session, ticker, since, cutoff))
    return data


INTRADAY_ALL = 5_000_000
"""Bars asked of ``load_intraday`` for "every bar in the range"."""


def load_symbol_intraday(
    session: Session,
    ticker: str,
    *,
    timeframe: str,
    end: datetime,
    start: datetime | None = None,
    lookback: int | None = None,
    feed: str | None = None,
    needs: Needs = Needs(),  # noqa: B008
    user_id: int | None = None,
    now: datetime | None = None,
) -> SymbolData:
    """A6.4: a symbol's closed ``timeframe`` bars opening at or before ``end``
    (naive UTC): from ``start`` plus ``lookback`` bars before it (all stored
    bars when either is None). ``feed`` None reads the best stored feed
    (``intraday.pick_feed``; :class:`intraday.NoIntradayData` when there is
    none). A partial newest bar is left out: rules judge closed bars only.

    Daily bars (``needs.daily``) are the whole stored daily history up to
    ``end``'s date, for ``daily.`` / ``weekly.`` / ``monthly.``; the
    evaluator aligns them to the session before each bar's."""
    ticker = ticker.upper()
    chosen, loaded = intraday_bars_for(
        session, ticker, timeframe=timeframe, end=end, start=start, lookback=lookback,
        feed=feed, now=now,
    )  # fmt: skip
    return intraday_symbol(
        session, ticker, loaded, timeframe=timeframe, feed=chosen, needs=needs, user_id=user_id,
        end=end,
    )  # fmt: skip


def intraday_bars_for(
    session: Session,
    ticker: str,
    *,
    timeframe: str,
    end: datetime,
    start: datetime | None = None,
    lookback: int | None = None,
    feed: str | None = None,
    now: datetime | None = None,
) -> tuple[str, list]:
    """(feed, closed ``IntradayOut`` bars) as :func:`load_symbol_intraday`
    reads them; the backtester keeps their ``Decimal`` prices for fills."""
    from stockviz.services.bars.intraday import (
        NoIntradayData,
        coverage,
        load_intraday,
        pick_feed,
    )
    from stockviz.services.instruments import instrument_ids

    venue = venue_for_ticker(ticker)
    instrument_id = instrument_ids(session, [ticker]).get(ticker)
    if instrument_id is None:
        raise NoIntradayData(f"No intraday bars are stored for {ticker}.")
    chosen = pick_feed(coverage(session, instrument_id), timeframe, feed, ticker)

    def bars_of(**kw):
        return load_intraday(
            session, instrument_id, timeframe, venue=venue, feed=chosen, now=now, **kw
        )

    end = instant(end).to_pydatetime()
    if start is None or lookback is None:
        loaded = bars_of(bars_wanted=INTRADAY_ALL, to=end)
    else:
        start = instant(start).to_pydatetime()
        window = bars_of(bars_wanted=INTRADAY_ALL, from_=start, to=end)
        warm = (
            bars_of(bars_wanted=lookback + (0 if window else 1),
                    to=start - timedelta(microseconds=1))
            if lookback + (0 if window else 1) > 0
            else []
        )  # fmt: skip
        loaded = [*warm, *window]
    return chosen, [b for b in loaded if not b.partial]


def intraday_symbol(
    session: Session,
    ticker: str,
    loaded: list,
    *,
    timeframe: str,
    feed: str,
    needs: Needs = Needs(),  # noqa: B008
    user_id: int | None = None,
    end: datetime | None = None,
) -> SymbolData:
    """A :class:`SymbolData` over loaded intraday bars, with the daily bars,
    benchmark, facts, news and drawings ``needs`` asks for."""
    from stockviz.services.event_study import benchmark_for
    from stockviz.services.instruments import instrument_ids

    venue = venue_for_ticker(ticker)
    instrument_id = instrument_ids(session, [ticker]).get(ticker)
    assert instrument_id is not None
    chosen = feed
    end = end or (loaded[-1].ts if loaded else datetime(1970, 1, 1))
    frame, closed, sessions = intraday_frame(loaded)
    data = SymbolData(
        ticker, venue, frame, timeframe=timeframe, closed_at=closed, sessions=sessions, feed=chosen
    )
    last_day = loaded[-1].session_date if loaded else end.date()
    first_day = loaded[0].session_date if loaded else end.date()
    if needs.daily or needs.delivery or needs.benchmark or needs.drawings:
        rows = _daily_rows(session, ticker, venue, start=None, end=last_day, lookback=None)
        daily = bars_frame(rows)
        if needs.delivery:
            loaded_any = _fill_delivery(
                session, instrument_id, daily, rows[0][0] if rows else last_day, last_day
            )
            data = replace(data, delivery_loaded=loaded_any)
        data = replace(data, daily=daily)
        if needs.benchmark:
            bench_ticker = benchmark_for(ticker)
            if bench_ticker is not None:
                bench = _benchmark(session, bench_ticker, rows[0][0] if rows else first_day,
                                   last_day)  # fmt: skip
                data = replace(data, benchmark=bench, benchmark_ticker=bench_ticker)
    if needs.fundamentals:
        data = replace(data, fundamentals=_fundamentals(session, ticker, instrument_id, last_day))
    if needs.drawings and user_id is not None:
        data = replace(data, drawings=load_drawings(session, user_id, instrument_id))
    if needs.news:
        cutoff = datetime.fromtimestamp(int(closed[-1]) / 1e9, UTC) if len(closed) else end
        since = datetime.combine(first_day - timedelta(days=400), time.min, tzinfo=UTC)
        data = replace(data, news=_news(session, ticker, since, cutoff.replace(tzinfo=UTC)))
    return data


__all__ = [
    "BAR_COLUMNS",
    "DAILY",
    "INTRADAY_ALL",
    "Needs",
    "SymbolData",
    "bars_frame",
    "instant",
    "intraday_bars_for",
    "intraday_frame",
    "intraday_symbol",
    "load_drawings",
    "load_symbol",
    "load_symbol_intraday",
    "session_close_ns",
]
