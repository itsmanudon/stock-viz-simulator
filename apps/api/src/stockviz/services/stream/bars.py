"""One-minute bars from ticks, in memory (A6.5).

:class:`MinuteBarBuilder` keeps one open bar per symbol:

- A tick in the open bar's minute updates it (high, low, close, volume).
- A tick in a later minute closes the open bar (returned) and opens a new one.
- A tick for a minute already closed is **late**: it is counted and dropped,
  never written into a bar the worker has stored and judged.
- :meth:`due` closes every bar whose minute ended more than ``grace`` ago at
  the wall clock (a live feed with a quiet symbol); a replay closes bars on
  the next minute's tick and :meth:`flush` at the end.
- A :class:`FeedBar` from the feed (a provider's own minute bar) replaces the
  open bar of its minute and is closed at once.

Bars come out with the builder's ``feed`` and ``source`` (``replayed`` /
``replay_file`` for a replay; ``iex`` / ``alpaca_iex_live`` from A6.6), so a
replayed bar can never pass for a live one.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from stockviz.services.feeds.base import MINUTE, FeedBar, FeedTag, Tick

DEFAULT_GRACE = timedelta(seconds=5)


def minute_of(instant: datetime) -> datetime:
    return instant.astimezone(UTC).replace(second=0, microsecond=0)


@dataclass
class _Open:
    ts: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int


@dataclass
class MinuteBarBuilder:
    feed: FeedTag
    source: str
    grace: timedelta = DEFAULT_GRACE
    late_ticks: int = 0
    _open: dict[str, _Open] = field(default_factory=dict)
    _closed_through: dict[str, datetime] = field(default_factory=dict)

    def _bar(self, symbol: str, bar: _Open) -> FeedBar:
        self._closed_through[symbol] = bar.ts
        return FeedBar(
            symbol=symbol, ts=bar.ts, open=bar.open, high=bar.high, low=bar.low,
            close=bar.close, volume=bar.volume, feed=self.feed, source=self.source,
        )  # fmt: skip

    def _late(self, symbol: str, minute: datetime) -> bool:
        done = self._closed_through.get(symbol)
        return done is not None and minute <= done

    def add(self, event: Tick | FeedBar) -> list[FeedBar]:
        """Take one event; return the bars it closed, oldest first."""
        symbol = event.symbol.upper()
        out: list[FeedBar] = []
        if isinstance(event, FeedBar):
            minute = minute_of(event.ts)
            if self._late(symbol, minute):
                self.late_ticks += 1
                return out
            current = self._open.pop(symbol, None)
            if current is not None and current.ts < minute:
                out.append(self._bar(symbol, current))
            out.append(self._bar(symbol, _Open(minute, event.open, event.high, event.low,
                                               event.close, event.volume)))  # fmt: skip
            return out
        minute = minute_of(event.ts)
        if self._late(symbol, minute):
            self.late_ticks += 1
            return out
        current = self._open.get(symbol)
        if current is not None and current.ts == minute:
            current.high = max(current.high, event.price)
            current.low = min(current.low, event.price)
            current.close = event.price
            current.volume += event.size
            return out
        if current is not None and current.ts < minute:
            out.append(self._bar(symbol, current))
        elif current is not None:  # an older minute than the open bar's
            self.late_ticks += 1
            return out
        self._open[symbol] = _Open(minute, event.price, event.price, event.price, event.price,
                                   event.size)  # fmt: skip
        return out

    def due(self, now: datetime) -> list[FeedBar]:
        """Close every open bar whose minute ended ``grace`` before ``now``."""
        out: list[FeedBar] = []
        for symbol, bar in sorted(self._open.items(), key=lambda kv: (kv[1].ts, kv[0])):
            if bar.ts + MINUTE + self.grace <= now:
                out.append(self._bar(symbol, bar))
        for b in out:
            self._open.pop(b.symbol, None)
        return out

    def flush(self) -> list[FeedBar]:
        """Close every open bar (the stream ended)."""
        out = [
            self._bar(s, b) for s, b in sorted(self._open.items(), key=lambda kv: (kv[1].ts, kv[0]))
        ]
        self._open.clear()
        return out


def as_replayed(bar: FeedBar, source: str) -> FeedBar:
    """A stored bar copied into the replayed feed (the warm-up before a replay)."""
    return replace(bar, feed="replayed", source=source)
