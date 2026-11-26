"""SimulatedFeed: stored minutes replayed as a stream, labelled "Replayed" (A6.3).

Never live. It serves tests, India (the owner's ``file`` minutes, locally)
and evenings when the US is closed; A6.5's stream worker reads it through the
same ``stream`` interface as a live feed.

- **Ticks per bar** (deterministic, one to four): the open at the bar's open
  instant, then the low and the high in the bar's direction (an up bar,
  close >= open, visits the low first; a down bar the high first), then the
  close. They sit at +0 s, +15 s, +30 s and +45 s. A price equal to the one
  before is merged into it, so a flat bar is one tick. The bar's volume is
  split evenly over its ticks, the remainder on the last.
- **Order:** by instant, then symbol: two symbols interleave as they would
  on a live feed.
- **From an instant:** ``start_at`` skips every bar opening before it.
- **Speed:** ``speed`` x real time (60 = a minute a second); ``0`` replays
  as fast as possible. The wait between two events is their gap / speed,
  through an injected async sleep (tests never wait).
- ``mode="bars"`` yields each :class:`FeedBar` once it is complete (at its
  close, open + 1 minute) instead of ticks.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Literal

from sqlmodel import Session, col, select

from stockviz.models.intraday import IntradayBar
from stockviz.services.feeds.base import (
    MINUTE,
    AsyncSleep,
    Capabilities,
    FeedBar,
    Tick,
    utc,
)
from stockviz.services.instruments import instrument_ids

TICK_OFFSETS = (0, 15, 30, 45)
REPLAYED = "Replayed"


def bar_ticks(bar: FeedBar) -> list[Tick]:
    """The bar's one to four ticks, in order."""
    if bar.close >= bar.open:
        path = [bar.open, bar.low, bar.high, bar.close]
    else:
        path = [bar.open, bar.high, bar.low, bar.close]
    prices: list[tuple[int, Decimal]] = []
    for offset, price in zip(TICK_OFFSETS, path, strict=True):
        if prices and prices[-1][1] == price:
            continue
        prices.append((offset, price))
    n = len(prices)
    share, rest = divmod(bar.volume, n)
    out: list[Tick] = []
    for index, (offset, price) in enumerate(prices):
        out.append(
            Tick(
                symbol=bar.symbol,
                ts=bar.ts + timedelta(seconds=offset),
                price=price,
                size=share + (rest if index == n - 1 else 0),
                feed=bar.feed,
                replayed=True,
            )
        )
    return out


@dataclass
class SimulatedFeed:
    bars: Sequence[FeedBar]
    speed: float = 0.0
    start_at: datetime | None = None
    mode: Literal["ticks", "bars"] = "ticks"
    sleep: AsyncSleep = asyncio.sleep
    _sorted: list[FeedBar] = field(init=False)

    name = "simulated"
    label = REPLAYED
    capabilities = Capabilities(
        history=True,
        stream=True,
        coverage=("iex", "sip", "kite", "file"),
        notes="Replays stored intraday_bars; never live.",
    )

    def __post_init__(self) -> None:
        if self.speed < 0:
            raise ValueError("speed must be 0 (as fast as possible) or positive")
        floor = utc(self.start_at) if self.start_at is not None else None
        self._sorted = sorted(
            (b for b in self.bars if floor is None or b.ts >= floor),
            key=lambda b: (b.ts, b.symbol),
        )

    @property
    def configured(self) -> bool:
        return True

    def minute_bars(self, symbol: str, start: datetime, end: datetime) -> list[FeedBar]:
        lo, hi = utc(start), utc(end)
        wanted = symbol.upper()
        return [b for b in self._sorted if b.symbol == wanted and lo <= b.ts < hi]

    def events(self, symbols: Sequence[str] | None = None) -> list[Tick | FeedBar]:
        """Every event in replay order, without pacing."""
        keep = {s.upper() for s in symbols} if symbols else None
        bars = [b for b in self._sorted if keep is None or b.symbol in keep]
        if self.mode == "bars":
            return list(bars)
        ticks = [t for b in bars for t in bar_ticks(b)]
        ticks.sort(key=lambda t: (t.ts, t.symbol))
        return list(ticks)

    @staticmethod
    def _instant(event: Tick | FeedBar) -> datetime:
        return event.ts if isinstance(event, Tick) else event.ts + MINUTE

    async def stream(self, symbols: Sequence[str]) -> AsyncIterator[Tick | FeedBar]:
        previous: datetime | None = None
        for event in self.events(symbols):
            instant = self._instant(event)
            if previous is not None and self.speed > 0:
                gap = (instant - previous).total_seconds()
                if gap > 0:
                    await self.sleep(gap / self.speed)
            previous = instant
            yield event

    @classmethod
    def from_store(
        cls,
        session: Session,
        tickers: Iterable[str],
        *,
        feed: str,
        start: datetime,
        end: datetime,
        **options: object,
    ) -> SimulatedFeed:
        """Load stored 1-minute ``intraday_bars`` of one feed (read only)."""
        ids = instrument_ids(session, [t.upper() for t in tickers])
        by_id = {iid: ticker for ticker, iid in ids.items()}
        lo = utc(start).replace(tzinfo=None)
        hi = utc(end).replace(tzinfo=None)
        rows = session.exec(
            select(IntradayBar).where(
                col(IntradayBar.instrument_id).in_(list(by_id)),
                IntradayBar.feed == feed,
                IntradayBar.interval == "1m",
                col(IntradayBar.ts) >= lo,
                col(IntradayBar.ts) < hi,
            )
        ).all()
        bars = [
            FeedBar(
                symbol=by_id[row.instrument_id],
                ts=utc(row.ts),
                open=row.open,
                high=row.high,
                low=row.low,
                close=row.close,
                volume=int(row.volume),
                feed=row.feed,  # pyright: ignore[reportArgumentType]
                source=row.source,
            )
            for row in rows
        ]
        return cls(bars=bars, **options)  # pyright: ignore[reportArgumentType]
