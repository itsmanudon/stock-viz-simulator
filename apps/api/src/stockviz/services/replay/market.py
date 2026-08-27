"""Server-owned historical PriceBar access for a ReplaySession.

Replay never calls unconstrained ``latest_bar``. Every query is clipped to the
session's frozen ``start_at`` / ``end_at`` and the current clock ``current_at``.

``PriceBar.ts`` is treated as a naive UTC session timestamp. Replay
``observed_at`` is that timestamp labeled UTC — not a vendor close print, and
not ``datetime.now``. Bar N cannot influence execution until ``current_at``
is bar N.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlmodel import Session, select

from stockviz.models import PriceBar, ReplaySession
from stockviz.services.replay.errors import ReplayNoMarketError, ReplayRangeError
from stockviz.services.replay.timeutil import as_aware_utc, as_naive_utc
from stockviz.services.simulation import MarketSnapshot

REPLAY_INTERVAL = "1d"


def _ticker_bars(ticker: str):
    return select(PriceBar).where(
        PriceBar.ticker == ticker,
        PriceBar.interval == REPLAY_INTERVAL,
    )


def resolve_replay_start(session: Session, *, ticker: str, requested: datetime) -> PriceBar:
    """First stored 1d bar at-or-after ``requested`` (UTC-normalized)."""

    ts = as_naive_utc(requested)
    bar = session.exec(
        _ticker_bars(ticker).where(PriceBar.ts >= ts).order_by(PriceBar.ts.asc()).limit(1)  # type: ignore[attr-defined]
    ).first()
    if bar is None:
        raise ReplayRangeError(f"No stored 1d bar for {ticker!r} at or after {ts.isoformat()}")
    return bar


def resolve_replay_end(session: Session, *, ticker: str, requested: datetime | None) -> PriceBar:
    """Last stored 1d bar at-or-before ``requested``, or the latest stored bar.

    The resolved ``ts`` is persisted as ``end_at`` so later ingest cannot extend
    the session horizon.
    """

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
    return bar


def count_replay_bars(
    session: Session, *, ticker: str, start_ts: datetime, end_ts: datetime
) -> int:
    rows = list(
        session.exec(
            _ticker_bars(ticker).where(PriceBar.ts >= start_ts, PriceBar.ts <= end_ts)
        ).all()
    )
    return len(rows)


def get_session_bar(session: Session, replay: ReplaySession) -> PriceBar:
    """The currently observable 1d bar. Never returns a bar after ``current_at``."""

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
    return bar


def get_next_session_bar(session: Session, replay: ReplaySession) -> PriceBar | None:
    """Next stored 1d bar after ``current_at`` and at-or-before ``end_at``."""

    return session.exec(
        _ticker_bars(replay.ticker)
        .where(PriceBar.ts > replay.current_at, PriceBar.ts <= replay.end_at)
        .order_by(PriceBar.ts.asc())  # type: ignore[attr-defined]
        .limit(1)
    ).first()


def get_visible_replay_history(session: Session, replay: ReplaySession) -> list[PriceBar]:
    """Bars in ``[start_at, current_at]`` clipped to ``end_at``. Never future bars."""

    return list(
        session.exec(
            _ticker_bars(replay.ticker)
            .where(
                PriceBar.ts >= replay.start_at,
                PriceBar.ts <= replay.current_at,
                PriceBar.ts <= replay.end_at,
            )
            .order_by(PriceBar.ts.asc())  # type: ignore[attr-defined]
        ).all()
    )


def snapshot_from_bar(bar: PriceBar, *, observed_at: datetime) -> MarketSnapshot:
    """Kernel snapshot for a stored bar. ``observed_at`` is the replay clock instant."""

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
    """Authoritative current snapshot. Prices come from stored PriceBar rows."""

    bar = get_session_bar(session, replay)
    return snapshot_from_bar(bar, observed_at=replay.current_at)
