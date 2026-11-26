"""A6.3: feed and broker interfaces, the adapters, rate limits, SimulatedFeed.

Every adapter runs against the hand-written fixtures in ``fixtures/feeds``
(documented shapes, invented numbers) through a fake HTTP function: no
provider is called and no real key exists here.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import httpx
import pytest

from stockviz.services.feeds.alpaca import AlpacaFeed, SipTooRecent, alpaca_symbol, sip_allowed
from stockviz.services.feeds.base import (
    Backoff,
    BrokerProvider,
    FeedAuthError,
    FeedBar,
    FeedNetworkError,
    FeedNotConfigured,
    FeedProvider,
    FeedProviderError,
    FeedRateError,
    NotSupported,
    Tick,
    classify_status,
    reconnecting,
    us_symbol,
)
from stockviz.services.feeds.finnhub import FinnhubFeed
from stockviz.services.feeds.massive import MassiveFeed
from stockviz.services.feeds.ratelimit import RateLimiter, estimate_seconds
from stockviz.services.feeds.registry import BROKERS, FEED_CLASSES, build_feed
from stockviz.services.feeds.simulated import SimulatedFeed, bar_ticks
from stockviz.services.feeds.tiingo import TiingoFeed, chunks, tiingo_symbol
from stockviz.settings import get_settings
from tests.feed_helpers import FakeClock, FakeHttp, fixture, response

KEY = "PKFAKE-KEY-DO-NOT-LEAK"
SECRET = "fake-secret-DO-NOT-LEAK"
OPEN = datetime(2025, 3, 3, 14, 30, tzinfo=UTC)  # 09:30 New York (EST)
CLOSE = datetime(2025, 3, 3, 21, 0, tzinfo=UTC)
LATER = datetime(2025, 3, 10, tzinfo=UTC)


def _alpaca(http: FakeHttp, clock: FakeClock | None = None, **kw) -> AlpacaFeed:
    clock = clock or FakeClock()
    return AlpacaFeed(
        key=KEY, secret=SECRET, get=http, clock=clock, sleep=clock.sleep, now=lambda: LATER, **kw
    )


# --- Interfaces -----------------------------------------------------------------


def test_every_adapter_meets_the_protocol_and_registry() -> None:
    settings = get_settings().model_copy(update={"massive_api_key": ""})
    for name in FEED_CLASSES:
        feed = build_feed(name, settings)
        assert isinstance(feed, FeedProvider)
        assert feed.name == name
        assert not feed.configured
        assert KEY not in repr(feed)
    assert isinstance(SimulatedFeed(bars=[]), FeedProvider)
    broker = BROKERS["zerodha"]
    assert isinstance(broker, BrokerProvider)
    for answer in (
        broker.status(),
        broker.login_url(),
        broker.import_fills(b""),
        broker.export_basket([]),
    ):
        assert not answer.supported and "A6.11" in answer.reason


def test_capabilities_match_the_documented_free_plans() -> None:
    assert AlpacaFeed.capabilities.coverage == ("iex", "sip")
    assert AlpacaFeed.capabilities.symbols_limit == 30
    assert AlpacaFeed.capabilities.rate_limits[0].calls == 200
    assert TiingoFeed.capabilities.coverage == ("iex",)
    assert [r.calls for r in TiingoFeed.capabilities.rate_limits] == [50, 1000]
    assert MassiveFeed.capabilities.coverage == ("sip",)
    assert MassiveFeed.capabilities.history_days == 730
    assert MassiveFeed.capabilities.rate_limits[0].calls == 5
    assert not FinnhubFeed.capabilities.history


def test_not_configured_refuses_before_any_request() -> None:
    http = FakeHttp([])
    for feed in (
        AlpacaFeed(key=KEY, secret="", get=http),
        TiingoFeed(get=http),
        MassiveFeed(get=http),
    ):
        assert not feed.configured
        with pytest.raises(FeedNotConfigured):
            feed.minute_bars("AAPL", OPEN, CLOSE)
    assert http.calls == []


def test_us_symbols_only() -> None:
    assert us_symbol(" aapl ") == "AAPL"
    assert alpaca_symbol("BRK-B") == "BRK.B"
    assert tiingo_symbol("BRK.B") == "brk-b"
    for bad in ("RELIANCE.NS", "500325.BO", "^NSEI", "^GSPC", "VOD.L", "", "A B"):
        with pytest.raises(ValueError):
            us_symbol(bad)
    feed = _alpaca(FakeHttp([]))
    with pytest.raises(ValueError):
        feed.minute_bars("TCS.NS", OPEN, CLOSE)


def test_streams_are_not_built_yet_with_the_reason() -> None:
    for feed in (_alpaca(FakeHttp([])), TiingoFeed(key=KEY), MassiveFeed(key=KEY)):
        with pytest.raises(NotSupported, match=r"A6\.5"):
            feed.stream(["AAPL"])
    with pytest.raises(NotSupported, match="premium"):
        FinnhubFeed(key=KEY).minute_bars("AAPL", OPEN, CLOSE)


# --- Alpaca -------------------------------------------------------------------


def test_alpaca_parses_pages_to_utc_iex_bars() -> None:
    http = FakeHttp(
        [
            response(200, fixture("alpaca_bars_page1.json")),
            response(200, fixture("alpaca_bars_page2.json")),
        ]
    )
    bars = _alpaca(http).minute_bars("BRK-B", OPEN, CLOSE)
    # The bar opening at 21:00 (the close, ``end``) is outside [start, end).
    assert [b.ts for b in bars] == [OPEN + timedelta(minutes=i) for i in range(3)]
    first = bars[0]
    assert first.symbol == "BRK-B" and first.feed == "iex" and first.source == "alpaca_iex"
    assert first.open == Decimal("480.10") and first.volume == 1200
    assert first.ts.tzinfo is UTC or first.ts.utcoffset() == timedelta(0)
    url, params, headers = http.calls[0]
    assert url == "https://data.alpaca.markets/v2/stocks/BRK.B/bars"
    assert params["timeframe"] == "1Min" and params["feed"] == "iex"
    assert params["adjustment"] == "split" and params["limit"] == "10000"
    assert params["start"] == "2025-03-03T14:30:00Z" and params["end"] == "2025-03-03T21:00:00Z"
    assert headers == {"APCA-API-KEY-ID": KEY, "APCA-API-SECRET-KEY": SECRET}
    assert "page_token" not in params
    assert http.calls[1][1]["page_token"] == "SEFORC1XUklUVEVOLVBBR0UtMg=="


def test_alpaca_empty_bars_and_repeated_page_token() -> None:
    assert (
        _alpaca(FakeHttp([response(200, fixture("alpaca_bars_empty.json"))])).minute_bars(
            "AAPL", OPEN, CLOSE
        )
        == []
    )
    page = {"bars": [], "next_page_token": "SAME"}
    with pytest.raises(FeedProviderError, match="repeated"):
        _alpaca(FakeHttp([response(200, page), response(200, page)])).minute_bars(
            "AAPL", OPEN, CLOSE
        )


def test_alpaca_sip_only_when_the_end_is_15_minutes_old() -> None:
    now = datetime(2025, 3, 3, 20, 0, tzinfo=UTC)
    assert sip_allowed(now - timedelta(minutes=15), now)
    assert not sip_allowed(now - timedelta(minutes=14, seconds=59), now)
    http = FakeHttp([response(200, {"bars": [], "next_page_token": None})])
    feed = AlpacaFeed(key=KEY, secret=SECRET, feed="sip", get=http, now=lambda: now)
    with pytest.raises(SipTooRecent):
        feed.minute_bars("AAPL", OPEN, now - timedelta(minutes=10))
    assert http.calls == []
    assert feed.minute_bars("AAPL", OPEN, now - timedelta(minutes=15)) == []
    assert http.calls[0][1]["feed"] == "sip"
    assert feed.source == "alpaca_sip"


def test_alpaca_rejects_malformed_rows_without_values() -> None:
    bad = {"bars": [{"t": "2025-03-03T14:30:00", "o": 1, "h": 1, "l": 1, "c": 1, "v": 1}]}
    with pytest.raises(FeedProviderError, match="time zone"):
        _alpaca(FakeHttp([response(200, bad)])).minute_bars("AAPL", OPEN, CLOSE)
    impossible = {"bars": [{"t": "2025-03-03T14:30:00Z", "o": 5, "h": 4, "l": 3, "c": 4, "v": 1}]}
    with pytest.raises(FeedProviderError, match="impossible"):
        _alpaca(FakeHttp([response(200, impossible)])).minute_bars("AAPL", OPEN, CLOSE)


# --- Tiingo -------------------------------------------------------------------


def test_tiingo_iex_offsets_become_utc_and_requests_chunk() -> None:
    http = FakeHttp([response(200, fixture("tiingo_iex_prices.json"))])
    feed = TiingoFeed(key=KEY, get=http)
    bars = feed.minute_bars("AAPL", OPEN, CLOSE)
    assert [b.ts for b in bars] == [OPEN, OPEN + timedelta(minutes=1), OPEN + timedelta(minutes=2)]
    assert {b.feed for b in bars} == {"iex"} and {b.source for b in bars} == {"tiingo_iex"}
    url, params, headers = http.calls[0]
    assert url == "https://api.tiingo.com/iex/aapl/prices"
    assert params == {
        "startDate": "2025-03-03",
        "endDate": "2025-03-03",
        "resampleFreq": "1min",
        "columns": "open,high,low,close,volume",
    }
    assert headers["Authorization"] == f"Token {KEY}"
    assert chunks(date(2025, 3, 1), date(2025, 3, 12)) == [
        (date(2025, 3, 1), date(2025, 3, 5)),
        (date(2025, 3, 6), date(2025, 3, 10)),
        (date(2025, 3, 11), date(2025, 3, 12)),
    ]
    http = FakeHttp([response(200, []) for _ in range(3)])
    TiingoFeed(key=KEY, get=http).minute_bars(
        "AAPL", datetime(2025, 3, 1, tzinfo=UTC), datetime(2025, 3, 13, tzinfo=UTC)
    )
    assert [c[1]["startDate"] for c in http.calls] == ["2025-03-01", "2025-03-06", "2025-03-11"]


def test_tiingo_daily_and_error_object() -> None:
    http = FakeHttp([response(200, fixture("tiingo_daily_prices.json"))])
    days = TiingoFeed(key=KEY, get=http).daily_bars("AAPL", date(2025, 3, 3), date(2025, 3, 4))
    assert [d.session_date for d in days] == [date(2025, 3, 3), date(2025, 3, 4)]
    assert days[1].div_cash == Decimal("0.25") and days[0].adj_close == Decimal("238.3")
    assert http.calls[0][0] == "https://api.tiingo.com/tiingo/daily/aapl/prices"
    http = FakeHttp([response(200, fixture("tiingo_error.json"))])
    with pytest.raises(FeedProviderError) as caught:
        TiingoFeed(key=KEY, get=http).minute_bars("AAPL", OPEN, CLOSE)
    assert "SECRET-ECHO" not in str(caught.value)


# --- Massive ------------------------------------------------------------------


def test_massive_reuses_the_shadow_adapter_and_tags_sip() -> None:
    http = FakeHttp(
        [
            response(200, fixture("massive_minutes_page1.json")),
            response(200, fixture("massive_minutes_page2.json")),
        ]
    )
    bars = MassiveFeed(key=KEY, get=http).minute_bars("MSFT", OPEN, CLOSE)
    # The 08:00 New York minute is before the asked start (regular hours).
    assert [b.ts for b in bars] == [OPEN, OPEN + timedelta(minutes=1)]
    assert {b.feed for b in bars} == {"sip"} and {b.source for b in bars} == {"massive"}
    assert bars[1].volume == 7000  # fractional volume rounded
    first_url, first_params, headers = http.calls[0]
    assert first_url == (
        "https://api.massive.com/v2/aggs/ticker/MSFT/range/1/minute/2025-03-03/2025-03-03"
    )
    assert first_params == {"adjusted": "true", "sort": "asc", "limit": "50000"}
    assert headers == {"Authorization": f"Bearer {KEY}"}
    next_url = http.calls[1][0]
    assert "apiKey" not in next_url and "cursor=HANDWRITTEN" in next_url


def test_massive_error_status_text_is_replaced() -> None:
    http = FakeHttp([response(200, fixture("massive_error.json"))])
    with pytest.raises(FeedProviderError) as caught:
        MassiveFeed(key=KEY, get=http).minute_bars("MSFT", OPEN, CLOSE)
    assert "SECRET-ECHO" not in str(caught.value) and "Unknown API Key" not in str(caught.value)


def test_massive_chunks_a_long_range_by_month() -> None:
    http = FakeHttp(
        [response(200, {"status": "OK", "adjusted": True, "results": []}) for _ in range(3)]
    )
    MassiveFeed(key=KEY, get=http).minute_bars(
        "MSFT", datetime(2025, 1, 2, 15, tzinfo=UTC), datetime(2025, 3, 3, 21, tzinfo=UTC)
    )
    assert [c[0].rsplit("/", 2)[-2:] for c in http.calls] == [
        ["2025-01-02", "2025-01-31"],
        ["2025-02-01", "2025-03-02"],
        ["2025-03-03", "2025-03-03"],
    ]


# --- Errors -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "error"),
    [(401, FeedAuthError), (403, FeedAuthError), (429, FeedRateError), (500, FeedNetworkError),
     (503, FeedNetworkError), (400, FeedProviderError), (422, FeedProviderError)],
)  # fmt: skip
def test_http_status_classification(status: int, error: type) -> None:
    assert isinstance(classify_status("Alpaca", status), error)


def test_errors_never_carry_the_key_or_body(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    body = {"message": f"bad key {KEY} {SECRET}"}
    cases = [
        (response(401, body), FeedAuthError, "auth"),
        (response(403, body), FeedAuthError, "auth"),
        (httpx.ConnectError(f"https://x/?apiKey={KEY}"), FeedNetworkError, "network"),
        (httpx.ReadTimeout(f"timeout {KEY}"), FeedNetworkError, "network"),
        (response(200, b"<html>" + KEY.encode()), FeedProviderError, "provider"),
    ]
    for item, error, kind in cases:
        with pytest.raises(error) as caught:
            _alpaca(FakeHttp([item])).minute_bars("AAPL", OPEN, CLOSE)
        text = str(caught.value)
        assert caught.value.kind == kind
        assert KEY not in text and SECRET not in text and "apiKey" not in text
        assert caught.value.__cause__ is None or KEY not in str(caught.value.__cause__)
        assert caught.value.summary == f"Alpaca {kind} error"
    assert KEY not in caplog.text and SECRET not in caplog.text


def test_429_waits_its_retry_after_then_classifies() -> None:
    clock = FakeClock()
    ok = response(200, {"bars": [], "next_page_token": None})
    http = FakeHttp([response(429, {}, {"Retry-After": "7"}), ok])
    assert _alpaca(http, clock).minute_bars("AAPL", OPEN, CLOSE) == []
    assert clock.slept == [7.0]
    clock = FakeClock()
    http = FakeHttp([response(429, {}) for _ in range(3)])
    with pytest.raises(FeedRateError):
        _alpaca(http, clock).minute_bars("AAPL", OPEN, CLOSE)
    assert clock.slept == [60.0, 60.0] and len(http.calls) == 3


# --- Rate limits --------------------------------------------------------------


def test_token_bucket_on_a_fake_clock() -> None:
    clock = FakeClock()
    feed = MassiveFeed(key=KEY, clock=clock, sleep=clock.sleep)
    for _ in range(5):
        feed.limiter.acquire()
    assert clock.slept == []  # a full bucket: five at once
    feed.limiter.acquire()
    assert clock.slept == [pytest.approx(12.0)]  # 5 a minute: one every 12 s
    clock.now += 60
    for _ in range(5):
        feed.limiter.acquire()
    assert len(clock.slept) == 1


def test_tiingo_hourly_and_daily_buckets() -> None:
    clock = FakeClock()
    limiter = RateLimiter.from_specs(
        TiingoFeed.capabilities.rate_limits, clock=clock, sleep=clock.sleep
    )
    for _ in range(51):
        limiter.acquire()
    assert clock.slept == [pytest.approx(72.0)]  # 50 an hour: one every 72 s
    assert estimate_seconds(TiingoFeed.capabilities.rate_limits, 50) == 0
    assert estimate_seconds(TiingoFeed.capabilities.rate_limits, 100) == pytest.approx(3600)
    assert estimate_seconds(MassiveFeed.capabilities.rate_limits, 25) == pytest.approx(240)
    assert estimate_seconds(AlpacaFeed.capabilities.rate_limits, 200) == 0


def test_adapters_take_tokens_per_request() -> None:
    clock = FakeClock()
    pages = [response(200, {"status": "OK", "adjusted": True, "results": []}) for _ in range(7)]
    feed = MassiveFeed(key=KEY, get=FakeHttp(pages), clock=clock, sleep=clock.sleep)
    # 2024-09-01 to 2025-02-28 New York: seven 30-day requests at 5 a minute.
    feed.minute_bars("MSFT", datetime(2024, 9, 2, tzinfo=UTC), datetime(2025, 3, 1, tzinfo=UTC))
    assert len(clock.slept) == 2 and feed.limiter.waited == pytest.approx(24.0)


# --- Stream reconnect ---------------------------------------------------------


def test_reconnecting_backs_off_and_stops_on_auth() -> None:
    attempts: list[int] = []
    slept: list[float] = []

    async def sleep(seconds: float) -> None:
        slept.append(seconds)

    def connect() -> AsyncIterator[int]:
        async def gen() -> AsyncIterator[int]:
            attempts.append(1)
            if len(attempts) <= 2:
                raise FeedNetworkError("Alpaca", "dropped")
            if len(attempts) == 3:
                raise FeedRateError("Alpaca", "limit", retry_after=30)
            yield 1
            yield 2

        return gen()

    seen: list[tuple[int, str]] = []

    async def run() -> list[int]:
        return [
            x
            async for x in reconnecting(
                connect,
                backoff=Backoff(base=1, factor=2, cap=10),
                sleep=sleep,
                on_reconnect=lambda n, e: seen.append((n, e.kind)),
            )
        ]

    assert asyncio.run(run()) == [1, 2]
    assert slept == [1, 2, 30]
    assert seen == [(1, "network"), (2, "network"), (3, "rate")]

    def refused() -> AsyncIterator[int]:
        async def gen() -> AsyncIterator[int]:
            raise FeedAuthError("Alpaca", "refused")
            yield 0

        return gen()

    async def run_refused() -> None:
        async for _ in reconnecting(refused, sleep=sleep):
            pass

    slept.clear()
    with pytest.raises(FeedAuthError):
        asyncio.run(run_refused())
    assert slept == []

    def always_down() -> AsyncIterator[int]:
        async def gen() -> AsyncIterator[int]:
            raise FeedNetworkError("Alpaca", "down")
            yield 0

        return gen()

    async def run_down() -> None:
        async for _ in reconnecting(always_down, backoff=Backoff(max_attempts=3), sleep=sleep):
            pass

    with pytest.raises(FeedNetworkError):
        asyncio.run(run_down())
    assert len(slept) == 3


# --- SimulatedFeed ------------------------------------------------------------


def _bar(symbol: str, minute: int, o: str, h: str, lo: str, c: str, v: int = 10) -> FeedBar:
    return FeedBar(
        symbol=symbol,
        ts=OPEN + timedelta(minutes=minute),
        open=Decimal(o),
        high=Decimal(h),
        low=Decimal(lo),
        close=Decimal(c),
        volume=v,
        feed="file",
        source="bulk_1m",
    )


def test_ticks_follow_the_bar_direction_and_split_volume() -> None:
    up = bar_ticks(_bar("A", 0, "10", "12", "9", "11", v=10))
    assert [t.price for t in up] == [Decimal(x) for x in ("10", "9", "12", "11")]
    assert [t.ts - OPEN for t in up] == [timedelta(seconds=s) for s in (0, 15, 30, 45)]
    assert [t.size for t in up] == [2, 2, 2, 4]
    down = bar_ticks(_bar("A", 0, "10", "12", "9", "9.5"))
    assert [t.price for t in down] == [Decimal(x) for x in ("10", "12", "9", "9.5")]
    flat = bar_ticks(_bar("A", 0, "10", "10", "10", "10", v=7))
    assert len(flat) == 1 and flat[0].size == 7
    assert all(t.replayed and t.label == "Replayed" and t.feed == "file" for t in up)


def test_simulated_order_start_and_bars_mode() -> None:
    bars = [
        _bar("B", 1, "5", "5", "5", "5"),
        _bar("A", 1, "1", "1", "1", "1"),
        _bar("A", 0, "1", "1", "1", "1"),
        _bar("B", 0, "5", "5", "5", "5"),
    ]
    feed = SimulatedFeed(bars=bars)
    assert [(e.symbol, e.ts) for e in feed.events()] == [
        ("A", OPEN),
        ("B", OPEN),
        ("A", OPEN + timedelta(minutes=1)),
        ("B", OPEN + timedelta(minutes=1)),
    ]
    later = SimulatedFeed(bars=bars, start_at=OPEN + timedelta(minutes=1))
    assert {e.ts for e in later.events()} == {OPEN + timedelta(minutes=1)}
    assert [e.symbol for e in feed.events(["b"])] == ["B", "B"]
    bar_mode = SimulatedFeed(bars=bars, mode="bars")
    assert all(isinstance(e, FeedBar) for e in bar_mode.events())
    assert feed.minute_bars("A", OPEN, OPEN + timedelta(minutes=1)) == [bars[2]]
    assert SimulatedFeed.label == "Replayed"


def test_simulated_speed_paces_with_the_injected_sleep() -> None:
    bars = [_bar("A", 0, "10", "12", "9", "11"), _bar("A", 2, "11", "11", "11", "11")]
    slept: list[float] = []

    async def sleep(seconds: float) -> None:
        slept.append(seconds)

    async def collect(feed: SimulatedFeed) -> list[Tick | FeedBar]:
        return [e async for e in feed.stream(["A"])]

    ticks = asyncio.run(collect(SimulatedFeed(bars=bars, speed=60, sleep=sleep)))
    assert len(ticks) == 5
    # 15 s gaps at 60x = 0.25 s; then 75 s (00:45 -> 02:00) = 1.25 s.
    assert slept == [0.25, 0.25, 0.25, 1.25]
    slept.clear()
    asyncio.run(collect(SimulatedFeed(bars=bars, speed=0, sleep=sleep)))
    assert slept == []
    slept.clear()
    asyncio.run(collect(SimulatedFeed(bars=bars, speed=1, mode="bars", sleep=sleep)))
    assert slept == [120.0]
    with pytest.raises(ValueError):
        SimulatedFeed(bars=bars, speed=-1)


def test_simulated_from_store_reads_stored_minutes(session) -> None:
    from stockviz.models.intraday import IntradayBar
    from stockviz.services.instruments import resolve_symbol
    from tests.symbols import seed_symbols

    seed_symbols(session, "TCS.NS", currency="INR")
    inst = resolve_symbol(session, "TCS.NS")
    assert inst is not None and inst.id is not None
    for i in range(3):
        ts = datetime(2025, 3, 3, 3, 45) + timedelta(minutes=i)
        session.add(
            IntradayBar(
                instrument_id=inst.id,
                feed="file",
                interval="1m",
                ts=ts,
                open=Decimal("100"),
                high=Decimal("101"),
                low=Decimal("99"),
                close=Decimal("100.5"),
                volume=40,
                source="bulk_1m",
                available_at=ts + timedelta(minutes=1),
            )
        )
    session.commit()
    feed = SimulatedFeed.from_store(
        session,
        ["TCS.NS"],
        feed="file",
        start=datetime(2025, 3, 3, 3, 46, tzinfo=UTC),
        end=datetime(2025, 3, 4, tzinfo=UTC),
    )
    events = feed.events()
    assert len(events) == 8 and {e.symbol for e in events} == {"TCS.NS"}
    assert events[0].ts == datetime(2025, 3, 3, 3, 46, tzinfo=UTC)
