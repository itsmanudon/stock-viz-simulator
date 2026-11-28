"""The stream worker's loop (A6.5): ticks in, stored bars and firings out.

For each event from a feed's ``stream`` (``SimulatedFeed`` now, ``AlpacaFeed``
from A6.6):

1. :class:`~stockviz.services.stream.bars.MinuteBarBuilder` builds one-minute
   bars in memory. A bar closes on the next minute's tick, by the wall clock
   plus a grace for a live feed, or when the stream ends.
2. **Store.** A closed bar inside the venue's session is written to
   ``intraday_bars`` with the stream's feed (``replayed`` for a replay, so a
   replayed bar never sits among real ones), ``available_at`` its close
   (clipped at the session close). A bar outside every session is counted,
   not stored. Writing is idempotent: a rerun inserts nothing.
3. **Tell the charts.** ``NOTIFY intraday_bar`` in the same transaction
   (``hub.notify_bar``), so the API's server-sent events carry only stored
   bars.
4. **Judge.** Every active intraday rule alert on the symbol whose setup
   version reads this stream's feed (``auto`` or the replayed source feed)
   is judged on each of its timeframe's bars that this minute closed, with
   A6.4's :func:`~stockviz.services.alerts.intraday.judge_bar` (point mode,
   state per bar instant, dedupe per alert and bar: a rerun fires nothing).
   Rules compile once per setup version.
5. **Deliver at once.** A firing goes through ``fire`` and
   ``on_alert_fired`` in the bar's transaction; after the commit the worker
   drains the due deliveries (``delivery.drain``) instead of waiting for the
   scheduler's next pass.
6. **Status.** ``feed_streams`` (one row per stream name) records the state,
   the symbols, the last tick and bar and the counters, in the same
   transaction.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from sqlmodel import Session

from stockviz.models import AlertEvent, AlertRepeat
from stockviz.models.feed_stream import FeedStream
from stockviz.services.alerts.intraday import intraday_alerts, judge_bar
from stockviz.services.bars.intraday import NoIntradayData
from stockviz.services.dsl import CompiledRule, RuleError
from stockviz.services.dsl.data import load_symbol_intraday
from stockviz.services.feeds.backfill import write_rows
from stockviz.services.feeds.base import MINUTE, FeedBar, FeedTag, Tick
from stockviz.services.instruments import instrument_ids
from stockviz.services.markets.calendar import (
    SessionHours,
    session_minutes,
    venue_for_ticker,
    venue_zone,
)
from stockviz.services.stream.bars import DEFAULT_GRACE, MinuteBarBuilder
from stockviz.services.stream.hub import BarEvent, notify_bar

logger = logging.getLogger(__name__)

WAIT_SECONDS = 1.0
"""How often a live stream with no events checks for bars to close."""


def aware_now() -> datetime:
    return datetime.now(UTC)


def _naive(instant: datetime) -> datetime:
    return instant.astimezone(UTC).replace(tzinfo=None) if instant.tzinfo else instant


@dataclass(frozen=True)
class StreamSpec:
    name: str
    """``feed_streams.name``: ``simulated`` or (A6.6) ``alpaca``."""
    label: str
    """The badge the stream's bars and firings carry: ``Replayed``, ``IEX only``."""
    bar_feed: FeedTag
    """The ``intraday_bars.feed`` the worker writes."""
    source: str
    """``intraday_bars.source``: ``replay_<feed>`` or ``alpaca_iex_live``."""
    version_feeds: frozenset[str]
    """Setup version feeds this stream judges (``auto`` and the bars' feed)."""
    wall_clock: bool = False
    """Live feeds close a quiet symbol's bar by the clock; a replay by its ticks."""
    grace: timedelta = DEFAULT_GRACE


def live_spec() -> StreamSpec:
    """A6.6: Alpaca's live IEX minute bars (``source`` ``alpaca_iex_live``)."""
    return StreamSpec(
        name="alpaca", label="IEX only", bar_feed="iex", source="alpaca_iex_live",
        version_feeds=frozenset({"auto", "iex"}), wall_clock=True,
    )  # fmt: skip


def replay_spec(source_feed: str) -> StreamSpec:
    """A ``SimulatedFeed`` replay of stored ``source_feed`` minutes."""
    return StreamSpec(
        name="simulated", label="Replayed", bar_feed="replayed", source=f"replay_{source_feed}",
        version_feeds=frozenset({"auto", source_feed}),
    )  # fmt: skip


@dataclass
class StreamReport:
    ticks: int = 0
    bars_closed: int = 0
    bars_written: int = 0
    bars_off_session: int = 0
    late_ticks: int = 0
    bars_judged: int = 0
    fired: int = 0
    event_ids: list[int] = field(default_factory=list)
    delivered: int = 0
    skipped: list[str] = field(default_factory=list)


Publish = Callable[[Session, BarEvent], None]


class StreamWorker:
    def __init__(
        self,
        spec: StreamSpec,
        symbols: Sequence[str],
        *,
        session_factory: Callable[[], Session],
        clock: Callable[[], datetime] = aware_now,
        deliver: bool = True,
        publish: Publish = notify_bar,
        judge_from: datetime | None = None,
        stop_at: datetime | None = None,
    ) -> None:
        self.spec = spec
        self.symbols = sorted({s.upper() for s in symbols})
        self.session_factory = session_factory
        self.clock = clock
        self.deliver = deliver
        self.publish = publish
        self.builder = MinuteBarBuilder(feed=spec.bar_feed, source=spec.source, grace=spec.grace)
        self.report = StreamReport()
        self._rules: dict[int, CompiledRule | None] = {}
        self._sessions: dict[tuple[str, date], SessionHours | None] = {}
        self._ids: dict[str, int] = {}
        self._last_tick: datetime | None = None
        # Alerts are judged on bars opening at or after this instant: the
        # stream's first bar unless given, so a replay's warm-up (or bars
        # stored before a live start) is context, never a firing.
        self.judge_from = _naive(judge_from) if judge_from is not None else None
        # A6.6: a live stream stops here (the session's close plus a grace).
        self.stop_at = stop_at
        # Set by :meth:`request_stop` (the live CLI's SIGTERM/SIGINT handler).
        self._stop_requested = False

    # --- lifecycle ------------------------------------------------------------

    async def run(self, events: AsyncIterator[Tick | FeedBar]) -> StreamReport:
        with self.session_factory() as session:
            self._ids = instrument_ids(session, self.symbols)
            missing = [s for s in self.symbols if s not in self._ids]
            if missing:
                raise ValueError(f"no instrument for {', '.join(missing)}")
            self._status(session, "streaming", started=True)
            session.commit()
        queue: asyncio.Queue[Tick | FeedBar | BaseException | None] = asyncio.Queue(maxsize=1000)

        async def pump() -> None:
            try:
                async for event in events:
                    await queue.put(event)
            except BaseException as exc:  # handed to the loop, which re-raises it
                await queue.put(exc)
                return
            await queue.put(None)

        task = asyncio.create_task(pump())
        try:
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=WAIT_SECONDS)
                except TimeoutError:
                    self._close_due()
                    if self._past_stop():
                        break
                    continue
                if item is None:
                    break
                if isinstance(item, BaseException):
                    raise item
                self.report.ticks += 1
                self._last_tick = item.ts
                for bar in self.builder.add(item):
                    self.close_bar(bar)
                self._close_due()
                if self._past_stop():
                    break
            for bar in self.builder.flush():
                self.close_bar(bar)
        except BaseException as exc:
            self._finish("error", f"{type(exc).__name__}: the stream stopped")
            raise
        finally:
            task.cancel()
        self.report.late_ticks = self.builder.late_ticks
        self._finish("closed", None)
        return self.report

    def request_stop(self) -> None:
        """Stop at the next tick or wait (within ``WAIT_SECONDS``), as at the close.

        Open bars are flushed and the stream's row ends ``closed``, so a
        ``kill`` of the worker's PID is a clean stop, not an ``error``.
        """
        self._stop_requested = True

    def _past_stop(self) -> bool:
        if self._stop_requested:
            return True
        return self.stop_at is not None and self.clock() >= self.stop_at

    def _close_due(self) -> None:
        if self.spec.wall_clock:
            for bar in self.builder.due(self.clock()):
                self.close_bar(bar)

    def _finish(self, state: str, error: str | None) -> None:
        with self.session_factory() as session:
            self._status(session, state, error=error, stopped=True)
            session.commit()

    def _status(
        self,
        session: Session,
        state: str,
        *,
        started: bool = False,
        stopped: bool = False,
        error: str | None = None,
        bar_at: datetime | None = None,
    ) -> None:
        now = _naive(self.clock())
        row = session.get(FeedStream, self.spec.name)
        if row is None or started:
            if row is None:
                row = FeedStream(name=self.spec.name, label=self.spec.label, state=state)
            row.started_at = now
            row.stopped_at = None
            row.last_tick_at = None
            row.last_bar_at = None
            row.bars_written = 0
            row.alerts_fired = 0
        row.label = self.spec.label
        row.state = state
        row.symbols = list(self.symbols)
        row.error = error
        row.updated_at = now
        if stopped:
            row.stopped_at = now
        if self._last_tick is not None:
            row.last_tick_at = _naive(self._last_tick)
        if bar_at is not None:
            row.last_bar_at = _naive(bar_at)
        row.bars_written = self.report.bars_written
        row.alerts_fired = self.report.fired
        session.add(row)

    # --- one closed bar -------------------------------------------------------

    def _hours(self, ticker: str, ts: datetime) -> SessionHours | None:
        venue = venue_for_ticker(ticker)
        day = ts.astimezone(venue_zone(venue)).date()
        key = (venue, day)
        if key not in self._sessions:
            self._sessions[key] = session_minutes(day, venue)
        hours = self._sessions[key]
        return hours if hours is not None and hours.contains(ts) else None

    def close_bar(self, bar: FeedBar) -> list[AlertEvent]:
        """Store, announce and judge one closed minute bar; deliver firings."""
        self.report.bars_closed += 1
        hours = self._hours(bar.symbol, bar.ts)
        if hours is None:
            self.report.bars_off_session += 1
            return []
        closed_at = min(bar.ts + MINUTE, hours.close)
        if self.judge_from is None:
            self.judge_from = _naive(bar.ts)
        fired: list[AlertEvent] = []
        with self.session_factory() as session:
            if bar.symbol not in self._ids:
                self._ids.update(instrument_ids(session, [bar.symbol]))
            row = {
                "instrument_id": self._ids[bar.symbol],
                "feed": bar.feed,
                "interval": "1m",
                "ts": _naive(bar.ts),
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "volume": bar.volume,
                "source": bar.source,
                "file_id": None,
                "ingested_at": _naive(self.clock()),
                "available_at": _naive(closed_at),
            }
            inserted = write_rows(session, [row])
            self.report.bars_written += inserted
            if inserted:
                self.publish(session, BarEvent.of(bar, closed_at))
            fired = self._judge(session, bar.symbol, closed_at)
            self._status(session, "streaming", bar_at=bar.ts)
            session.commit()
            ids = [e.id for e in fired if e.id is not None]
        self.report.event_ids.extend(ids)
        if fired and self.deliver:
            from stockviz.services.delivery import drain

            with self.session_factory() as session:
                result = drain(session)  # the delivery outbox's own clock
                self.report.delivered += result.sent
        return fired

    def _rule(self, version_id: int, text: str, timeframe: str) -> CompiledRule | None:
        if version_id not in self._rules:
            from stockviz.services.dsl import compile_rule

            try:
                self._rules[version_id] = compile_rule(text, timeframe=timeframe)
            except RuleError:
                self._rules[version_id] = None
                self.report.skipped.append(
                    f"setup version {version_id}: its rule no longer compiles"
                )
        return self._rules[version_id]

    def _judge(self, session: Session, ticker: str, closed_at: datetime) -> list[AlertEvent]:
        """Judge the symbol's alerts on every bar this minute closed."""
        fired: list[AlertEvent] = []
        recorded = _naive(self.clock())
        for alert, version in intraday_alerts(session, ticker):
            if version.feed not in self.spec.version_feeds:
                continue
            if alert.repeat == AlertRepeat.ONCE and alert.triggered_at is not None:
                continue
            assert version.id is not None
            rule = self._rule(version.id, version.rule_text, version.timeframe)
            if rule is None:
                continue
            start = alert.last_bar_at or _naive(alert.armed_at or alert.created_at)
            if alert.last_fired_bar_at is not None:
                start = min(start, alert.last_fired_bar_at)
            try:
                data = load_symbol_intraday(
                    session, ticker, timeframe=version.timeframe, end=_naive(closed_at),
                    start=start, lookback=rule.lookback, feed=self.spec.bar_feed,
                    needs=rule.needs, user_id=alert.user_id, now=closed_at,
                )  # fmt: skip
            except NoIntradayData:
                continue
            for bar_at in data.instants:
                if alert.last_bar_at is not None and bar_at <= alert.last_bar_at:
                    continue
                if self.judge_from is not None and bar_at < self.judge_from:
                    continue
                judged = judge_bar(
                    session, alert, rule, data, bar_at, now=closed_at, recorded_at=recorded
                )
                if judged is None:
                    continue
                self.report.bars_judged += 1
                if judged.fired is not None:
                    self.report.fired += 1
                    fired.append(judged.fired)
                    if alert.repeat == AlertRepeat.ONCE:
                        break
        return fired


def prime_replayed(session: Session, bars: Iterable[FeedBar], *, source: str) -> int:
    """Copy stored bars into the replayed feed without judging them: the
    warm-up a replay's rules need before its first streamed bar. Idempotent."""
    ids: dict[str, int] = {}
    rows: list[dict[str, object]] = []
    for bar in bars:
        if bar.symbol not in ids:
            ids.update(instrument_ids(session, [bar.symbol]))
        rows.append(
            {
                "instrument_id": ids[bar.symbol],
                "feed": "replayed",
                "interval": "1m",
                "ts": _naive(bar.ts),
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "volume": bar.volume,
                "source": source,
                "file_id": None,
                "ingested_at": _naive(aware_now()),
                "available_at": _naive(bar.ts + MINUTE),
            }
        )
    return write_rows(session, rows)
