"""What a replay chart may show besides its bars (A4.6, M9.1): indicators and
events, both cut at the session clock.

- **Indicators** run on the session's visible bars (``start_at`` to
  ``current_at``) warmed up on the stored bars before ``start_at`` (all
  earlier than the clock), with the venue index's closes cut at
  ``current_at`` for the RS line. Nothing after the clock is loaded, so no
  value can depend on it; a value on a date equals the live chart's value on
  that date when the same warm-up is available.
- **Events** are the session's own fills and the Aegis news linked to the
  symbol whose ``available_at`` is at or before ``current_at`` (the stored
  bar's timestamp: conservative, a headline published during that session
  shows from the next bar). Earnings, dividends and splits are left out:
  their reported figures could be later than the clock. The A3.5 events
  route is never called from replay.
"""

from __future__ import annotations

import pandas as pd
from sqlmodel import Session, col, select

from stockviz.models import PriceBar, ReplaySession
from stockviz.schemas import FillEventOut, IndicatorsOut, NewsEventOut, NewsHeadlineOut
from stockviz.services.indicator_view import compute_bundle
from stockviz.services.indicators import engine
from stockviz.services.instruments import instrument_of
from stockviz.services.replay.market import (
    REPLAY_INTERVAL,
    get_visible_replay_history,
    get_warmup_bars,
)
from stockviz.services.replay.session import list_replay_fills
from stockviz.services.symbol_events import news_clusters

REPLAY_NEWS_RULE = (
    "News linked to the symbol whose available_at is at or before the replay clock (the "
    "current bar's timestamp), one marker per UTC day of available_at. A headline published "
    "during a session appears from the next bar. Titles, sources and links only."
)


def _bench_closes(db: Session, replay: ReplaySession) -> pd.Series | None:
    from stockviz.services.event_study import benchmark_for

    bench = benchmark_for(replay.ticker)
    if bench is None:
        return None
    rows = db.exec(
        select(PriceBar)
        .where(
            PriceBar.instrument_id == instrument_of(bench),
            PriceBar.interval == REPLAY_INTERVAL,
            col(PriceBar.ts) <= replay.current_at,
        )
        .order_by(col(PriceBar.ts))
    ).all()
    return pd.Series(
        [float(r.close) for r in rows],
        index=pd.DatetimeIndex([r.ts for r in rows]),
        dtype=float,
    )


def replay_indicators(
    db: Session, replay: ReplaySession, requests: list[engine.Request]
) -> IndicatorsOut:
    """``requests`` over the visible bars, warmed up on earlier stored bars."""
    rows = get_visible_replay_history(db, replay)
    lookback = max((r.lookback for r in requests), default=0)
    warmup = get_warmup_bars(db, replay, lookback) if rows else []
    ohlcv = [(r.ts, r.open, r.high, r.low, r.close, r.volume) for r in warmup + rows]
    # A6.9: the RS line reads the venue index's daily closes, so an intraday
    # session has none.
    needs_bench = replay.interval == REPLAY_INTERVAL and any(
        r.spec.needs_benchmark for r in requests
    )
    return compute_bundle(
        replay.ticker,
        replay.interval,
        requests,
        ohlcv,
        window_start=rows[0].ts if rows else None,
        warmup_bars=len(warmup),
        bench=_bench_closes(db, replay) if needs_bench else None,
    )


def replay_events(db: Session, replay: ReplaySession) -> list[NewsEventOut | FillEventOut]:
    """News known by the clock and the session's fills, oldest first."""
    start, end = replay.start_at.date(), replay.current_at.date()
    out: list[NewsEventOut | FillEventOut] = []
    for event in news_clusters(db, replay.ticker, start, end, available_until=replay.current_at):
        out.append(
            NewsEventOut(
                date=event.date,
                count=event.count or 0,
                sources=event.sources,
                headlines=[NewsHeadlineOut(**h.__dict__) for h in event.headlines],
            )
        )
    for fill in list_replay_fills(db, replay=replay):
        if fill.evaluated_at > replay.current_at:
            continue
        out.append(
            FillEventOut(
                date=fill.evaluated_at.date(),
                ts=fill.evaluated_at,
                side=fill.side,
                quantity=fill.quantity,
                price=fill.fill_price,
            )
        )
    out.sort(key=lambda e: (e.date, 0 if e.type == "news" else 1))
    return out


__all__ = ["REPLAY_NEWS_RULE", "replay_events", "replay_indicators"]
