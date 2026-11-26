"""Server-owned historical bar access for a ReplaySession.

Replay never calls unconstrained ``latest_bar``. Every query is clipped to the
session's frozen ``start_at`` / ``end_at`` and the current clock ``current_at``.

A daily session (``interval`` ``1d``) reads stored ``PriceBar`` rows, whose
``ts`` is a naive UTC session label. A6.9: an intraday session (``1m``,
``5m``, ``15m``, ``60m``) reads bars built from its feed's stored minutes
(``intraday.IntradaySource``), whose ``ts`` is the bar's open instant. Either
way the functions here return :class:`ReplayBar`. Replay ``observed_at`` is
the bar's ``ts`` labelled UTC — not a vendor close print, and not
``datetime.now``. Bar N cannot influence execution until ``current_at`` is
bar N.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlmodel import Session, select

from stockviz.models import PriceBar, ReplaySession, Symbol
from stockviz.services.bars.intraday import IntradayOut
from stockviz.services.instruments import instrument_of
from stockviz.services.replay.errors import (
    ReplayNoMarketError,
    ReplayRangeError,
    ReplaySymbolNotFound,
)
from stockviz.services.replay.intraday import DAILY, IntradaySource
from stockviz.services.replay.timeutil import as_aware_utc, as_naive_utc
from stockviz.services.simulation import MarketSnapshot

REPLAY_INTERVAL = DAILY
"""The daily interval (every session before A6.9)."""


@dataclass(frozen=True)
class ReplayBar:
    """One bar a session can see: a stored daily bar or an intraday bar."""

    ticker: str
    ts: datetime
    interval: str
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    closed_at: datetime | None = None
    """An intraday bar's close instant (naive UTC); None for a daily bar."""


def _from_price_bar(bar: PriceBar) -> ReplayBar:
    return ReplayBar(
        ticker=bar.ticker,
        ts=bar.ts,
        interval=bar.interval,
        open=bar.open,
        high=bar.high,
        low=bar.low,
        close=bar.close,
        volume=int(bar.volume),
    )


def _from_intraday(ticker: str, interval: str, bar: IntradayOut) -> ReplayBar:
    return ReplayBar(
        ticker=ticker,
        ts=bar.ts,
        interval=interval,
        open=bar.open,
        high=bar.high,
        low=bar.low,
        close=bar.close,
        volume=int(bar.volume),
        closed_at=bar.closed_at,
    )


def _source(replay: ReplaySession) -> IntradaySource | None:
    if replay.interval == DAILY:
        return None
    if replay.feed is None:
        raise ReplayNoMarketError(f"Replay session {replay.id} has no minute feed")
    return IntradaySource(replay.ticker, replay.interval, replay.feed)


def _ticker_bars(ticker: str):
    return select(PriceBar).where(
        PriceBar.instrument_id == instrument_of(ticker),
        PriceBar.interval == REPLAY_INTERVAL,
    )


def resolve_replay_start(
    session: Session,
    *,
    ticker: str,
    requested: datetime,
    source: IntradaySource | None = None,
) -> ReplayBar:
    """First bar at-or-after ``requested`` (UTC-normalized)."""

    ts = as_naive_utc(requested)
    if source is not None:
        found = source.first_at_or_after(session, ts)
        if found is None:
            raise ReplayRangeError(
                f"No stored {source.interval} bar for {ticker!r} at or after {ts.isoformat()}"
            )
        return _from_intraday(ticker, source.interval, found)
    bar = session.exec(
        _ticker_bars(ticker).where(PriceBar.ts >= ts).order_by(PriceBar.ts.asc()).limit(1)  # type: ignore[attr-defined]
    ).first()
    if bar is None:
        raise ReplayRangeError(f"No stored 1d bar for {ticker!r} at or after {ts.isoformat()}")
    return _from_price_bar(bar)


def resolve_replay_end(
    session: Session,
    *,
    ticker: str,
    requested: datetime | None,
    source: IntradaySource | None = None,
) -> ReplayBar:
    """Last bar at-or-before ``requested``, or the latest stored bar.

    The resolved ``ts`` is persisted as ``end_at`` so later ingest cannot extend
    the session horizon.
    """

    if source is not None:
        if requested is None:
            raise ReplayRangeError("An intraday replay session needs an end")
        ts = as_naive_utc(requested)
        found = source.last_at_or_before(session, ts)
        if found is None:
            raise ReplayRangeError(
                f"No stored {source.interval} bar for {ticker!r} at or before {ts.isoformat()}"
            )
        return _from_intraday(ticker, source.interval, found)
    stmt = _ticker_bars(ticker)
    if requested is not None:
        ts = as_naive_utc(requested)
        stmt = stmt.where(PriceBar.ts <= ts)
    bar = session.exec(stmt.order_by(PriceBar.ts.desc()).limit(1)).first()  # type: ignore[attr-defined]
    if bar is None:
        if requested is None:
            raise ReplayRangeError(f"No stored 1d bars for {ticker!r}")
        raise ReplayRangeError(
            f"No stored 1d bar for {ticker!r} at or before {as_naive_utc(requested).isoformat()}"
        )
    return _from_price_bar(bar)


def count_replay_bars(
    session: Session,
    *,
    ticker: str,
    start_ts: datetime,
    end_ts: datetime,
    source: IntradaySource | None = None,
) -> int:
    if source is not None:
        return len(source.between(session, start_ts, end_ts))
    rows = list(
        session.exec(
            _ticker_bars(ticker).where(PriceBar.ts >= start_ts, PriceBar.ts <= end_ts)
        ).all()
    )
    return len(rows)


def get_session_bar(session: Session, replay: ReplaySession) -> ReplayBar:
    """The currently observable bar. Never returns a bar after ``current_at``."""

    source = _source(replay)
    if source is not None:
        found = (
            source.at(session, replay.current_at)
            if replay.start_at <= replay.current_at <= replay.end_at
            else None
        )
        if found is None:
            raise ReplayNoMarketError(
                f"Replay session {replay.id} has no {replay.interval} bar at "
                f"{replay.current_at.isoformat()}"
            )
        return _from_intraday(replay.ticker, replay.interval, found)
    bar = session.exec(
        _ticker_bars(replay.ticker)
        .where(
            PriceBar.ts == replay.current_at,
            PriceBar.ts >= replay.start_at,
            PriceBar.ts <= replay.end_at,
            PriceBar.ts <= replay.current_at,
        )
        .limit(1)
    ).first()
    if bar is None:
        raise ReplayNoMarketError(
            f"Replay session {replay.id} has no stored 1d bar at {replay.current_at.isoformat()}"
        )
    return _from_price_bar(bar)


def get_next_session_bar(session: Session, replay: ReplaySession) -> ReplayBar | None:
    """Next bar after ``current_at`` and at-or-before ``end_at``."""

    source = _source(replay)
    if source is not None:
        found = source.after(session, replay.current_at, replay.end_at)
        return _from_intraday(replay.ticker, replay.interval, found) if found else None
    bar = session.exec(
        _ticker_bars(replay.ticker)
        .where(PriceBar.ts > replay.current_at, PriceBar.ts <= replay.end_at)
        .order_by(PriceBar.ts.asc())  # type: ignore[attr-defined]
        .limit(1)
    ).first()
    return _from_price_bar(bar) if bar is not None else None


def get_warmup_bars(session: Session, replay: ReplaySession, n: int) -> list[ReplayBar]:
    """Up to ``n`` bars before ``start_at``, oldest first: an indicator's
    warm-up. All are before the clock, so they leak nothing."""

    if n <= 0:
        return []
    source = _source(replay)
    if source is not None:
        return [
            _from_intraday(replay.ticker, replay.interval, b)
            for b in source.before(session, replay.start_at, n)
        ]
    rows = list(
        session.exec(
            _ticker_bars(replay.ticker)
            .where(PriceBar.ts < replay.start_at)
            .order_by(PriceBar.ts.desc())  # type: ignore[attr-defined]
            .limit(n)
        ).all()
    )
    rows.reverse()
    return [_from_price_bar(r) for r in rows]


def get_visible_replay_history(session: Session, replay: ReplaySession) -> list[ReplayBar]:
    """Bars in ``[start_at, current_at]`` clipped to ``end_at``. Never future bars."""

    source = _source(replay)
    if source is not None:
        upper = min(replay.current_at, replay.end_at)
        return [
            _from_intraday(replay.ticker, replay.interval, b)
            for b in source.between(session, replay.start_at, upper)
        ]
    rows = session.exec(
        _ticker_bars(replay.ticker)
        .where(
            PriceBar.ts >= replay.start_at,
            PriceBar.ts <= replay.current_at,
            PriceBar.ts <= replay.end_at,
        )
        .order_by(PriceBar.ts.asc())  # type: ignore[attr-defined]
    ).all()
    return [_from_price_bar(r) for r in rows]


def snapshot_from_bar(bar: ReplayBar | PriceBar, *, observed_at: datetime) -> MarketSnapshot:
    """Kernel snapshot for a bar. ``observed_at`` is the replay clock instant."""

    return MarketSnapshot(
        ticker=bar.ticker,
        observed_at=as_aware_utc(observed_at),
        interval=bar.interval,
        open=bar.open,
        high=bar.high,
        low=bar.low,
        close=bar.close,
        volume=Decimal(bar.volume),
    )


def market_snapshot_for_replay(session: Session, replay: ReplaySession) -> MarketSnapshot:
    """Authoritative current snapshot. Prices come from stored bars."""

    bar = get_session_bar(session, replay)
    return snapshot_from_bar(bar, observed_at=replay.current_at)


def get_replay_availability(
    session: Session, *, ticker: str
) -> tuple[Symbol, PriceBar, PriceBar, int]:
    """Stored 1d range for the launcher. Rejects unknown tickers.

    A4.6: any currency (the session trades in it); the router adds the lag."""

    ticker = ticker.strip().upper()
    symbol = session.get(Symbol, ticker)
    if symbol is None:
        raise ReplaySymbolNotFound(f"Symbol {ticker!r} not found")
    first = session.exec(_ticker_bars(ticker).order_by(PriceBar.ts.asc()).limit(1)).first()  # type: ignore[attr-defined]
    last = session.exec(_ticker_bars(ticker).order_by(PriceBar.ts.desc()).limit(1)).first()  # type: ignore[attr-defined]
    if first is None or last is None:
        raise ReplayRangeError(f"No stored 1d bars for {ticker!r}")
    return (
        symbol,
        first,
        last,
        count_replay_bars(session, ticker=ticker, start_ts=first.ts, end_ts=last.ts),
    )
