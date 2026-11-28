"""A6.5: the stream worker and the replayed half of the A6 done-when.

Synthetic minutes only (never the owner's files), on NSE sessions as in
``test_a64_intraday.py`` (IST = UTC + 5:30), stored as feed ``file`` and
replayed through ``SimulatedFeed`` into the worker. The done-when, replayed:
the worker writes each closing bar, the alert fires once at its bar's close
with ``feed = replayed``, the firings equal A6.4's judgement over the stored
bars (which equal the backtest's signals, proved there), and a rerun adds
no second bar or event.
"""

# pyright: reportAttributeAccessIssue=false, reportArgumentType=false

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from jose import jwt as jose_jwt
from sqlmodel import Session, func, select

from stockviz.models import (
    Alert,
    AlertEvent,
    AlertKind,
    AlertRepeat,
    DeliveryAttempt,
    FeedStream,
    Notification,
    NotificationChannel,
    User,
)
from stockviz.models.intraday import IntradayBar
from stockviz.services import delivery as delivery_mod
from stockviz.services.alerts.intraday import evaluate_intraday_alerts
from stockviz.services.bars import intraday as intraday_mod
from stockviz.services.dsl import compile_rule
from stockviz.services.feeds.base import FeedBar, Tick
from stockviz.services.feeds.simulated import SimulatedFeed, bar_ticks
from stockviz.services.instruments import resolve_symbol
from stockviz.services.setups import store
from stockviz.services.stream.bars import MinuteBarBuilder
from stockviz.services.stream.hub import BarEvent, BarHub, sse
from stockviz.services.stream.replay import plan_replay, warmup_sessions, watched
from stockviz.services.stream.worker import StreamSpec, StreamWorker, replay_spec
from stockviz.settings import get_settings
from stockviz.workers import stream as stream_cli
from tests.symbols import seed_symbols

IST = timedelta(hours=5, minutes=30)
TICKER = "TCS.NS"
LATER = datetime(2026, 11, 26, 12, tzinfo=UTC)
D1, D2, D3 = date(2024, 11, 4), date(2024, 11, 5), date(2024, 11, 6)
SECRET = get_settings().internal_api_token
RULE = "close crosses_above 105"
PATH = {(D1, "11:30"): 110.0, (D1, "13:30"): 100.0, (D2, "10:30"): 110.0, (D2, "12:30"): 100.0,
        (D2, "13:30"): 110.0, (D3, "11:00"): 100.0, (D3, "14:00"): 112.0}  # fmt: skip


@pytest.fixture(autouse=True)
def _clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(intraday_mod, "now_utc", lambda: LATER)


def _utc(day: date, hhmm: str) -> datetime:
    h, m = (int(x) for x in hhmm.split(":"))
    return datetime.combine(day, time(h, m)) - IST


def _aware(day: date, hhmm: str) -> datetime:
    return _utc(day, hhmm).replace(tzinfo=UTC)


def _step(changes: dict[tuple[date, str], float], base: float = 100.0):
    keys = sorted(changes)

    def price(day: date, local: datetime) -> float:
        value = base
        for k in keys:
            if (day, local.strftime("%H:%M")) >= k:
                value = changes[k]
        return value

    return price


def _seed(session: Session, price: Callable[[date, datetime], float], days=(D1, D2, D3)) -> None:
    """Every NSE minute; the bar moves through open/low/high/close so the
    replay's one-to-four ticks are exercised."""
    seed_symbols(session, TICKER, currency="INR")
    instrument = resolve_symbol(session, TICKER)
    assert instrument is not None and instrument.id is not None
    for day in days:
        ts = _utc(day, "09:15")
        while ts < _utc(day, "15:30"):
            p = Decimal(str(price(day, ts + IST)))
            session.add(
                IntradayBar(instrument_id=instrument.id, feed="file", interval="1m", ts=ts,
                            open=p, high=p + Decimal("0.5"), low=p - Decimal("0.5"), close=p,
                            volume=101, source="bulk_1m",
                            available_at=ts + timedelta(minutes=1))
            )  # fmt: skip
            ts += timedelta(minutes=1)
    session.commit()


def _user(session: Session, email: str) -> int:
    row = User(email=email, name=email.split("@")[0])
    session.add(row)
    session.commit()
    assert row.id is not None
    return row.id


def _alert(session: Session, email: str, rule: str = RULE, *, timeframe: str = "60m",
           feed: str = "auto", repeat=AlertRepeat.EVERY_CROSS) -> Alert:  # fmt: skip
    uid = _user(session, email)
    _setup, version = store.create_setup(session, uid, name="Hourly", kind="alert",
                                         rule=compile_rule(rule, timeframe=timeframe),
                                         timeframe=timeframe, feed=feed)  # fmt: skip
    alert = Alert(user_id=uid, ticker=TICKER, kind=AlertKind.RULE, setup_version_id=version.id,
                  params={"setup_name": "Hourly", "version": 1, "canonical": rule},
                  repeat=repeat, cooldown_sessions=1, armed_at=_utc(D1, "09:00"))  # fmt: skip
    session.add(alert)
    session.commit()
    return alert


def _events(session: Session, alert: Alert) -> list[AlertEvent]:
    return list(
        session.exec(
            select(AlertEvent).where(AlertEvent.alert_id == alert.id).order_by(AlertEvent.id)  # type: ignore[arg-type]
        ).all()
    )


def _count(session: Session, feed: str) -> int:
    return session.exec(select(func.count()).where(IntradayBar.feed == feed)).one()


class Published:
    def __init__(self) -> None:
        self.events: list[BarEvent] = []

    def __call__(self, _session: Session, event: BarEvent) -> None:
        self.events.append(event)


def _replay(session: Session, engine, *, start=D2, end=D3, publish=None, deliver=False):
    plan = plan_replay(session, [TICKER], source_feed="file", start=_aware(start, "00:00"),
                       end=_aware(end, "23:59"))  # fmt: skip
    worker = StreamWorker(
        replay_spec("file"), plan.tickers, session_factory=lambda: Session(engine),
        clock=lambda: LATER, deliver=deliver, publish=publish or Published(),
    )  # fmt: skip
    report = asyncio.run(worker.run(plan.feed.stream(plan.tickers)))
    session.expire_all()
    return plan, report


# --- bars from ticks --------------------------------------------------------------


def _feed_bar(minute: int, o: str, h: str, low: str, c: str, v: int = 100) -> FeedBar:
    return FeedBar(symbol="AAPL", ts=datetime(2026, 1, 5, 15, minute, tzinfo=UTC),
                   open=Decimal(o), high=Decimal(h), low=Decimal(low), close=Decimal(c),
                   volume=v, feed="iex", source="test")  # fmt: skip


def test_replayed_ticks_rebuild_the_stored_bars_exactly() -> None:
    bars = [_feed_bar(0, "10", "11", "9", "10.5", 101), _feed_bar(1, "10.5", "10.5", "10.5", "10.5"),
            _feed_bar(2, "10", "10.2", "8", "8.5", 7)]  # fmt: skip
    builder = MinuteBarBuilder(feed="replayed", source="replay_iex")
    out: list[FeedBar] = []
    for bar in bars:
        for tick in bar_ticks(bar):
            out += builder.add(tick)
    out += builder.flush()
    assert [(b.ts, b.open, b.high, b.low, b.close, b.volume) for b in out] == [
        (b.ts, b.open, b.high, b.low, b.close, b.volume) for b in bars
    ]
    assert {b.feed for b in out} == {"replayed"} and {b.source for b in out} == {"replay_iex"}


def test_late_ticks_are_dropped_and_quiet_bars_close_by_the_clock() -> None:
    builder = MinuteBarBuilder(feed="iex", source="alpaca_iex_live")
    t0 = datetime(2026, 1, 5, 15, 0, 10, tzinfo=UTC)
    tick = lambda ts, p: Tick(symbol="aapl", ts=ts, price=Decimal(p), size=5, feed="iex")  # noqa: E731
    assert builder.add(tick(t0, "10")) == []
    closed = builder.add(tick(t0 + timedelta(minutes=1), "11"))
    assert [b.close for b in closed] == [Decimal("10")] and closed[0].symbol == "AAPL"
    assert builder.add(tick(t0 + timedelta(seconds=20), "99")) == []  # the 15:00 bar is closed
    assert builder.late_ticks == 1
    minute = t0.replace(second=0) + timedelta(minutes=1)
    assert builder.due(minute + timedelta(minutes=1, seconds=4)) == []  # inside the grace
    due = builder.due(minute + timedelta(minutes=1, seconds=5))
    assert [b.ts for b in due] == [minute] and builder.flush() == []


def test_a_providers_own_bar_closes_at_once() -> None:
    builder = MinuteBarBuilder(feed="iex", source="alpaca_iex_live")
    first = _feed_bar(0, "10", "11", "9", "10.5")
    assert [b.ts for b in builder.add(first)] == [first.ts]
    assert builder.add(first) == [] and builder.late_ticks == 1


# --- the done-when, replayed ------------------------------------------------------


def test_replay_fires_like_the_stored_bars_and_never_twice(session: Session, engine) -> None:
    _seed(session, _step(PATH))
    replayed = _alert(session, "replay@stockviz.dev")
    other = _alert(session, "iex@stockviz.dev", feed="iex")  # another feed's version
    published = Published()
    plan, report = _replay(session, engine, publish=published)
    # Warm-up: the session before the window, copied unjudged.
    assert plan.primed == 375 and warmup_sessions(session, [TICKER]) == 2
    assert report.bars_written == 2 * 375 and report.bars_off_session == 0
    assert _count(session, "replayed") == 3 * 375
    assert len(published.events) == 2 * 375
    first = published.events[0]
    assert first.feed == "replayed" and first.replayed and first.badge == "Replayed"
    assert first.ts == "2024-11-05T03:45:00Z" and first.closed_at == "2024-11-05T03:46:00Z"

    events = _events(session, replayed)
    assert [e.bar_at for e in events] == [_utc(D2, "10:15"), _utc(D2, "13:15"), _utc(D3, "13:15")]
    assert {e.feed for e in events} == {"replayed"}
    assert "Replayed from stored bars, not live" in events[0].message
    assert events[0].created_at == LATER.replace(tzinfo=None)  # recorded when it fired
    # A version reading another feed is not this replay's: never judged.
    assert _events(session, other) == []
    session.refresh(other)
    assert other.last_bar_at is None
    # A6.4's judgement over the stored file bars (best feed: file before
    # replayed) gives the same bars, so the same backtest signals.
    stored = _alert(session, "stored@stockviz.dev")
    evaluate_intraday_alerts(session, since=_utc(D2, "09:15"), now=LATER)
    assert [e.bar_at for e in _events(session, stored)] == [e.bar_at for e in events]
    assert {e.feed for e in _events(session, stored)} == {"file"}

    # A rerun of the worker over the same minutes adds nothing.
    _plan2, again = _replay(session, engine, publish=published)
    assert again.bars_written == 0 and again.fired == 0
    assert len(_events(session, replayed)) == 3 and len(published.events) == 2 * 375
    assert _count(session, "replayed") == 3 * 375

    status = session.get(FeedStream, "simulated")
    assert status is not None and status.state == "closed" and status.symbols == [TICKER]
    assert status.last_bar_at == _utc(D3, "15:29") and status.bars_written == 0


def test_the_alert_fires_at_its_bars_close(session: Session, engine) -> None:
    """The 10:15 hourly bar fires when its last minute (11:14) closes, not before."""
    _seed(session, _step(PATH), days=(D1, D2))
    alert = _alert(session, "close@stockviz.dev")
    plan_replay(session, [TICKER], source_feed="file", start=_aware(D2, "00:00"),
                end=_aware(D2, "23:59"))  # fmt: skip
    worker = StreamWorker(replay_spec("file"), [TICKER], session_factory=lambda: Session(engine),
                          clock=lambda: LATER, deliver=False, publish=Published())  # fmt: skip
    feed = SimulatedFeed.from_store(session, [TICKER], feed="file", start=_aware(D2, "09:00"),
                                    end=_aware(D2, "23:59"), mode="bars")  # fmt: skip
    fired_at: list[str] = []
    for bar in feed.events([TICKER]):
        assert isinstance(bar, FeedBar)
        if worker.close_bar(replace(bar, feed="replayed")):
            fired_at.append((bar.ts + IST).strftime("%H:%M"))
    session.expire_all()
    # The 10:15 IST bar fires as its last minute, 11:14, closes.
    assert fired_at == ["11:14", "14:14"]
    assert [e.bar_at for e in _events(session, alert)] == [_utc(D2, "10:15"), _utc(D2, "13:15")]


def test_off_session_minutes_are_not_written(session: Session, engine) -> None:
    seed_symbols(session, "AAPL", currency="USD")
    published = Published()
    worker = StreamWorker(replay_spec("iex"), ["AAPL"], session_factory=lambda: Session(engine),
                          clock=lambda: LATER, deliver=False, publish=published)  # fmt: skip
    night = FeedBar(symbol="AAPL", ts=datetime(2026, 1, 6, 3, 0, tzinfo=UTC), open=Decimal(1),
                    high=Decimal(1), low=Decimal(1), close=Decimal(1), volume=1,
                    feed="replayed", source="replay_iex")  # fmt: skip
    day = replace(night, ts=datetime(2026, 1, 6, 15, 0, tzinfo=UTC))
    assert worker.close_bar(night) == [] and worker.close_bar(day) == []
    session.expire_all()
    assert worker.report.bars_off_session == 1 and worker.report.bars_written == 1
    assert _count(session, "replayed") == 1 and len(published.events) == 1


def test_a_firing_is_delivered_at_once(
    session: Session, engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(session, _step(PATH), days=(D1, D2))
    alert = _alert(session, "deliver@stockviz.dev")
    session.add(NotificationChannel(user_id=alert.user_id, channel="webhook", enabled=True,
                                    config={"url": "https://hooks.example.com/x"},
                                    secret="s" * 32))  # fmt: skip
    session.commit()
    sent: list[dict] = []
    monkeypatch.setattr(delivery_mod, "send", lambda _c, _u, body: sent.append(body))
    monkeypatch.setattr(delivery_mod, "server_available", lambda _ch: True)
    _plan, report = _replay(session, engine, end=D2, deliver=True)
    assert report.fired == 2 and report.delivered == 2 and len(sent) == 2
    rows = session.exec(select(DeliveryAttempt)).all()
    assert {r.status for r in rows} == {"sent"}
    notes = session.exec(select(Notification).where(Notification.user_id == alert.user_id)).all()
    assert len(notes) == 2 and (notes[0].data or {}).get("feed") == "replayed"


def test_a_stream_error_is_recorded(session: Session, engine) -> None:
    seed_symbols(session, "AAPL", currency="USD")

    async def broken():
        yield Tick(symbol="AAPL", ts=datetime(2026, 1, 6, 15, 0, tzinfo=UTC), price=Decimal(1),
                   size=1, feed="iex", replayed=True)  # fmt: skip
        raise ConnectionError("gone")

    worker = StreamWorker(replay_spec("iex"), ["AAPL"], session_factory=lambda: Session(engine),
                          clock=lambda: LATER, deliver=False, publish=Published())  # fmt: skip
    with pytest.raises(ConnectionError):
        asyncio.run(worker.run(broken()))
    session.expire_all()
    row = session.get(FeedStream, "simulated")
    assert row is not None and row.state == "error"
    assert row.error == "ConnectionError: the stream stopped"  # never the exception's text


def test_unknown_symbols_are_refused(engine) -> None:
    worker = StreamWorker(replay_spec("iex"), ["NOPE"], session_factory=lambda: Session(engine))
    with pytest.raises(ValueError, match="no instrument for NOPE"):
        asyncio.run(worker.run(SimulatedFeed(bars=[]).stream(["NOPE"])))


def test_a_live_stream_closes_quiet_bars_by_the_clock(session: Session, engine) -> None:
    seed_symbols(session, "AAPL", currency="USD")
    t0 = datetime(2026, 1, 6, 15, 0, 10, tzinfo=UTC)
    clock = {"now": t0}
    spec = StreamSpec(name="test_live", label="IEX only", bar_feed="iex", source="test_live",
                      version_feeds=frozenset({"auto", "iex"}), wall_clock=True)  # fmt: skip
    worker = StreamWorker(spec, ["AAPL"], session_factory=lambda: Session(engine),
                          clock=lambda: clock["now"], deliver=False, publish=Published())  # fmt: skip

    async def quiet():
        yield Tick(symbol="AAPL", ts=t0, price=Decimal(5), size=3, feed="iex")
        clock["now"] = t0 + timedelta(minutes=1)  # the bar is due (15:01:05 + grace)
        await asyncio.sleep(1.2)  # longer than the worker's wait

    report = asyncio.run(worker.run(quiet()))
    assert report.bars_written == 1 and report.bars_closed == 1
    session.expire_all()
    assert _count(session, "iex") == 1


# --- symbols and the CLI ----------------------------------------------------------


def test_watched_symbols_put_alert_symbols_first(session: Session) -> None:
    _seed(session, _step(PATH), days=(D1,))
    _alert(session, "watch@stockviz.dev")
    assert watched(session) == [TICKER]


def test_cli_refuses_without_a_window_or_a_key(capsys, monkeypatch) -> None:
    assert stream_cli.main(["--replay", "--symbols", TICKER]) == 2
    assert "--start" in capsys.readouterr().err
    assert stream_cli.main(["--feed", "alpaca"]) == 2  # conftest blanks the keys
    assert "Offline" in capsys.readouterr().err


# --- the hub and server-sent events -----------------------------------------------


def _event(ticker: str = TICKER) -> BarEvent:
    return BarEvent(ticker=ticker, feed="replayed", badge="Replayed", interval="1m",
                    ts="2024-11-05T03:45:00Z", closed_at="2024-11-05T03:46:00Z", open="1",
                    high="1", low="1", close="1", volume=5, replayed=True)  # fmt: skip


def test_hub_sends_each_subscriber_its_tickers_only() -> None:
    async def scenario():
        hub = BarHub(dsn=None)
        tcs = hub.subscribe([TICKER])
        other = hub.subscribe(["AAPL"])
        hub.publish(_event())
        await asyncio.sleep(0)
        assert tcs.queue.qsize() == 1 and other.queue.qsize() == 0
        for _ in range(300):
            hub.publish(_event())
        await asyncio.sleep(0.01)
        assert tcs.queue.qsize() == 256 and tcs.dropped > 0  # oldest dropped, never blocks
        hub.unsubscribe(tcs)
        hub.unsubscribe(other)
        assert hub.subscribers == 0

    asyncio.run(scenario())
    assert BarEvent.parse(_event().json()) == _event()
    assert BarEvent.parse("not json") is None
    assert sse(_event()).startswith("event: bar\ndata: {")


def test_sse_stream_sends_bars_and_validates_tickers(client: TestClient) -> None:
    from stockviz.routers import stream as stream_router

    async def scenario():
        hub = BarHub(dsn=None)

        class Req:
            async def is_disconnected(self) -> bool:
                return True

        gen = stream_router.events(Req(), hub, [TICKER], heartbeat=0.05)  # type: ignore[arg-type]
        assert await anext(gen) == ": connected\n\n"
        hub.publish(_event())
        assert (await anext(gen)).startswith("event: bar")
        with pytest.raises(StopAsyncIteration):  # heartbeat finds the client gone
            await anext(gen)
        assert hub.subscribers == 0

    asyncio.run(scenario())
    assert client.get("/v1/stream/bars", params={"tickers": " , "}).status_code == 422
    many = ",".join(f"T{i}" for i in range(11))
    assert client.get("/v1/stream/bars", params={"tickers": many}).status_code == 422


def test_broker_status_lists_streams(client: TestClient, session: Session) -> None:
    uid = _user(session, "status@stockviz.dev")
    session.add(FeedStream(name="simulated", label="Replayed", state="streaming",
                           symbols=[TICKER], updated_at=LATER.replace(tzinfo=None)
                           - timedelta(hours=1)))  # fmt: skip
    session.commit()
    token = jose_jwt.encode({"sub": str(uid)}, SECRET, "HS256")
    r = client.get("/v1/broker/feeds", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    [row] = r.json()["streams"]
    assert row["name"] == "simulated" and row["live"] is False
    assert row["state"] == "closed" and row["stale"] is True and row["symbols"] == [TICKER]


# --- A6.6: the live spec ------------------------------------------------------------


def test_live_spec_writes_iex_bars_and_stops_at_the_close(session: Session, engine) -> None:
    from stockviz.services.stream.worker import live_spec

    seed_symbols(session, "AAPL", currency="USD")
    spec = live_spec()
    assert (spec.name, spec.bar_feed, spec.source, spec.label) == (
        "alpaca", "iex", "alpaca_iex_live", "IEX only")  # fmt: skip
    t0 = datetime(2026, 1, 6, 15, 0, tzinfo=UTC)
    clock = {"now": t0 + timedelta(minutes=1, seconds=1)}
    worker = StreamWorker(spec, ["AAPL"], session_factory=lambda: Session(engine),
                          clock=lambda: clock["now"], deliver=False, publish=Published(),
                          stop_at=t0 + timedelta(minutes=3))  # fmt: skip

    async def live():
        bar = FeedBar(symbol="AAPL", ts=t0, open=Decimal(5), high=Decimal(6), low=Decimal(4),
                      close=Decimal(5), volume=10, feed="iex", source="alpaca_iex_live")  # fmt: skip
        yield bar
        clock["now"] = t0 + timedelta(minutes=3, seconds=1)  # past the stop
        yield replace(bar, ts=t0 + timedelta(minutes=1))
        await asyncio.sleep(60)  # a live feed never ends: the stop must end the run

    # The run ends at the stop although the feed never does (the wait_for
    # would raise otherwise). The feed may run ahead of the loop, so the
    # second bar can arrive after the stop has passed.
    report = asyncio.run(asyncio.wait_for(worker.run(live()), timeout=10))
    assert report.bars_written >= 1
    session.expire_all()
    assert _count(session, "iex") == report.bars_written


def test_live_cli_refuses_when_the_market_is_closed(capsys, monkeypatch) -> None:
    from stockviz.settings import get_settings

    monkeypatch.setenv("ALPACA_KEY_ID", "not-real")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "not-real")
    get_settings.cache_clear()
    monkeypatch.setattr(stream_cli, "datetime", _FrozenSunday)
    try:
        assert stream_cli.main(["--feed", "alpaca", "--symbols", "AAPL"]) == 2
        assert "closed" in capsys.readouterr().err
    finally:
        get_settings.cache_clear()


class _FrozenSunday(datetime):
    @classmethod
    def now(cls, tz=None):  # type: ignore[override]
        return datetime(2026, 11, 29, 16, 0, tzinfo=UTC)  # a Sunday


def test_a_stop_request_closes_a_live_stream_cleanly(session: Session, engine) -> None:
    """A6.6 live check: ``kill <pid>`` ends a live run as ``closed``, not ``error``."""
    from stockviz.services.stream.worker import live_spec

    seed_symbols(session, "AAPL", currency="USD")
    t0 = datetime(2026, 1, 6, 15, 0, tzinfo=UTC)
    clock = {"now": t0 + timedelta(seconds=30)}
    worker = StreamWorker(live_spec(), ["AAPL"], session_factory=lambda: Session(engine),
                          clock=lambda: clock["now"], deliver=False, publish=Published(),
                          stop_at=t0 + timedelta(hours=6))  # fmt: skip

    async def live():
        yield Tick(symbol="AAPL", ts=t0 + timedelta(seconds=5), price=Decimal(5), size=3,
                   feed="iex")  # fmt: skip
        worker.request_stop()  # what the SIGTERM handler does
        await asyncio.sleep(60)  # a live feed never ends: the request must end the run

    report = asyncio.run(asyncio.wait_for(worker.run(live()), timeout=10))
    assert report.bars_written == 1  # the open minute was flushed
    session.expire_all()
    row = session.get(FeedStream, "alpaca")
    assert row is not None and row.state == "closed" and row.error is None


def test_live_cli_stops_cleanly_on_sigterm() -> None:
    import os
    import signal

    class Worker:
        stopped = False

        def request_stop(self) -> None:
            self.stopped = True

        async def run(self, _events):
            os.kill(os.getpid(), signal.SIGTERM)
            for _ in range(50):
                if self.stopped:
                    return "report"
                await asyncio.sleep(0.01)
            raise AssertionError("SIGTERM did not reach request_stop")

    worker = Worker()
    assert asyncio.run(stream_cli._until_signalled(worker, None)) == "report"  # type: ignore[arg-type]
    assert worker.stopped
