"""Closed minute bars from the worker to open charts (A6.5).

**Worker side.** :func:`notify_bar` issues ``NOTIFY intraday_bar, '<json>'``
in the transaction that writes the bar, so a chart hears of a bar only once
it is stored (PostgreSQL delivers a notification at commit, and never for a
rolled-back write). SQLite (tests) has no ``NOTIFY``: the call is a no-op
there and tests publish to the hub directly.

**API side.** :class:`BarHub` fans the notifications out to server-sent
event subscribers (``GET /v1/stream/bars``). It ``LISTEN``s on its own
autocommit connection in a background thread, started by the first
subscriber and stopped when the last one leaves, so an API with no open
intraday chart (production today: no intraday bars) holds no connection.
Each subscriber has a bounded queue; a slow one loses its oldest events
rather than holding the others up (the chart refetches on a gap).

The payload is small (well under PostgreSQL's 8,000-byte limit): the ticker,
the feed and its badge, the bar's open and close instants and its OHLCV as
strings.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from sqlalchemy import text
from sqlmodel import Session

from stockviz.services.bars.intraday import FEED_BADGES
from stockviz.services.feeds.base import FeedBar

logger = logging.getLogger(__name__)

CHANNEL = "intraday_bar"
QUEUE_SIZE = 256
MAX_SUBSCRIBERS = 200
LISTEN_POLL_SECONDS = 1.0


def _iso(instant: datetime) -> str:
    aware = instant if instant.tzinfo else instant.replace(tzinfo=UTC)
    return aware.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class BarEvent:
    ticker: str
    feed: str
    badge: str
    interval: str
    ts: str
    closed_at: str
    open: str
    high: str
    low: str
    close: str
    volume: int
    replayed: bool

    @classmethod
    def of(cls, bar: FeedBar, closed_at: datetime) -> BarEvent:
        return cls(
            ticker=bar.symbol.upper(), feed=bar.feed, badge=FEED_BADGES.get(bar.feed, bar.feed),
            interval="1m", ts=_iso(bar.ts), closed_at=_iso(closed_at),
            open=str(bar.open), high=str(bar.high), low=str(bar.low), close=str(bar.close),
            volume=int(bar.volume), replayed=bar.feed == "replayed",
        )  # fmt: skip

    def json(self) -> str:
        return json.dumps(asdict(self), separators=(",", ":"))

    @classmethod
    def parse(cls, payload: str) -> BarEvent | None:
        try:
            data = json.loads(payload)
            return cls(**data)
        except (ValueError, TypeError):
            return None


def notify_bar(session: Session, event: BarEvent) -> None:
    """``NOTIFY`` in the caller's transaction (delivered at its commit)."""
    conn = session.connection()
    if conn.dialect.name != "postgresql":
        return
    conn.execute(text("SELECT pg_notify(:channel, :payload)"),
                 {"channel": CHANNEL, "payload": event.json()})  # fmt: skip


class Subscriber:
    def __init__(self, loop: asyncio.AbstractEventLoop, tickers: Iterable[str]) -> None:
        self.loop = loop
        self.tickers = frozenset(t.upper() for t in tickers)
        self.queue: asyncio.Queue[BarEvent] = asyncio.Queue(maxsize=QUEUE_SIZE)
        self.dropped = 0

    def offer(self, event: BarEvent) -> None:
        """Called on the subscriber's loop."""
        if event.ticker not in self.tickers:
            return
        if self.queue.full():
            self.queue.get_nowait()
            self.dropped += 1
        self.queue.put_nowait(event)


class HubFull(RuntimeError):
    pass


class BarHub:
    def __init__(self, dsn: str | None) -> None:
        self.dsn = dsn
        self._subs: set[Subscriber] = set()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    @property
    def subscribers(self) -> int:
        return len(self._subs)

    def subscribe(self, tickers: Iterable[str]) -> Subscriber:
        sub = Subscriber(asyncio.get_running_loop(), tickers)
        with self._lock:
            if len(self._subs) >= MAX_SUBSCRIBERS:
                raise HubFull("too many live chart connections")
            self._subs.add(sub)
            self._ensure_listener()
        return sub

    def unsubscribe(self, sub: Subscriber) -> None:
        with self._lock:
            self._subs.discard(sub)
            if not self._subs:
                self._stop.set()

    def publish(self, event: BarEvent) -> None:
        """Hand one event to every subscriber (thread-safe)."""
        with self._lock:
            subs = list(self._subs)
        for sub in subs:
            try:
                sub.loop.call_soon_threadsafe(sub.offer, event)
            except RuntimeError:  # the subscriber's loop has closed
                self.unsubscribe(sub)

    def _ensure_listener(self) -> None:
        if self.dsn is None:
            return
        if self._thread is not None and self._thread.is_alive() and not self._stop.is_set():
            return
        # A stopping thread exits on its own event; a fresh one takes over.
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._listen, args=(self._stop,), name="intraday-bar-listen", daemon=True
        )
        self._thread.start()

    def _listen(self, stop: threading.Event) -> None:
        import psycopg

        assert self.dsn is not None
        while not stop.is_set():
            try:
                with psycopg.connect(self.dsn, autocommit=True) as conn:
                    conn.execute(f"LISTEN {CHANNEL}")
                    while not stop.is_set():
                        for note in conn.notifies(timeout=LISTEN_POLL_SECONDS):
                            event = BarEvent.parse(note.payload)
                            if event is not None:
                                self.publish(event)
            except Exception:
                logger.warning("intraday bar listener lost its connection; retrying")
                stop.wait(5)


def listen_dsn(database_url: str) -> str | None:
    """A libpq DSN for ``LISTEN`` (None on SQLite)."""
    if not database_url.startswith("postgresql"):
        return None
    return database_url.replace("postgresql+psycopg://", "postgresql://", 1)


_hub: BarHub | None = None


def get_hub() -> BarHub:
    global _hub
    if _hub is None:
        from stockviz.settings import get_settings

        _hub = BarHub(listen_dsn(get_settings().database_url))
    return _hub


def sse(event: BarEvent) -> str:
    return f"event: bar\ndata: {event.json()}\n\n"
