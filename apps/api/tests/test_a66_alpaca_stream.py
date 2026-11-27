"""A6.6: the Alpaca IEX stream, against a fake socket (no network, no key used)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from stockviz.services.feeds.alpaca import (
    LIVE_SOURCE,
    STREAM_URL,
    AlpacaFeed,
)
from stockviz.services.feeds.base import (
    FeedAuthError,
    FeedBar,
    FeedProviderError,
    NotSupported,
)

CONNECTED = [{"T": "success", "msg": "connected"}]
AUTHED = [{"T": "success", "msg": "authenticated"}]
SUBSCRIBED = [{"T": "subscription", "trades": [], "quotes": [], "bars": ["AAPL", "BRK.B"]}]


def _bar(symbol: str, t: str, o=100.5, h=101, lo=100, c=100.75, v=1200) -> dict:
    return {"T": "b", "S": symbol, "o": o, "h": h, "l": lo, "c": c, "v": v, "vw": 100.6,
            "n": 12, "t": t}  # fmt: skip


class FakeSocket:
    def __init__(self, frames: list[list[dict]], *, drop_after: bool = True) -> None:
        self.frames = [json.dumps(f) for f in frames]
        self.sent: list[dict] = []
        self.drop_after = drop_after

    async def send(self, message: str) -> None:
        self.sent.append(json.loads(message))

    async def recv(self) -> str:
        if not self.frames:
            raise ConnectionResetError("closed")
        return self.frames.pop(0)


def _connector(*sockets: FakeSocket):
    queue = list(sockets)
    urls: list[str] = []

    @asynccontextmanager
    async def connect(url: str) -> AsyncIterator[FakeSocket]:
        urls.append(url)
        if not queue:
            raise OSError("no more connections")
        yield queue.pop(0)

    return connect, urls


def _feed(connect) -> AlpacaFeed:
    return AlpacaFeed(key="key-id-not-real", secret="secret-not-real", connect=connect)


async def _take(stream: AsyncIterator, n: int) -> list:
    out = []
    async for item in stream:
        out.append(item)
        if len(out) == n:
            break
    return out


def test_handshake_subscribe_and_bars() -> None:
    socket = FakeSocket([CONNECTED, AUTHED, SUBSCRIBED,
                         [_bar("AAPL", "2026-11-27T14:31:00Z"), _bar("BRK.B", "2026-11-27T14:31:00Z")],
                         [_bar("MSFT", "2026-11-27T14:32:00Z")],  # not ours: ignored
                         [_bar("AAPL", "2026-11-27T14:32:00Z", c=101)]])  # fmt: skip
    connect, urls = _connector(socket)
    bars = asyncio.run(_take(_feed(connect).stream(["AAPL", "BRK-B"]), 3))
    assert urls == [STREAM_URL]
    assert socket.sent[0] == {"action": "auth", "key": "key-id-not-real",
                              "secret": "secret-not-real"}  # fmt: skip
    assert socket.sent[1] == {"action": "subscribe", "bars": ["AAPL", "BRK.B"]}
    assert all(isinstance(b, FeedBar) for b in bars)
    assert [b.symbol for b in bars] == ["AAPL", "BRK-B", "AAPL"]
    first = bars[0]
    assert first.ts == datetime(2026, 11, 27, 14, 31, tzinfo=UTC)
    assert first.open == Decimal("100.5") and first.close == Decimal("100.75")
    assert first.volume == 1200 and first.feed == "iex" and first.source == LIVE_SOURCE


def test_bad_key_ends_the_stream_without_retrying() -> None:
    socket = FakeSocket([CONNECTED, [{"T": "error", "code": 402, "msg": "auth failed"}]])
    connect, urls = _connector(socket, FakeSocket([CONNECTED]))
    with pytest.raises(FeedAuthError) as caught:
        asyncio.run(_take(_feed(connect).stream(["AAPL"]), 1))
    assert len(urls) == 1
    assert "key-id-not-real" not in str(caught.value) and "secret" not in str(caught.value)


def test_insufficient_subscription_is_a_provider_error() -> None:
    socket = FakeSocket([CONNECTED, AUTHED, [{"T": "error", "code": 409, "msg": "x"}]])
    connect, _ = _connector(socket)
    with pytest.raises(FeedProviderError):
        asyncio.run(_take(_feed(connect).stream(["AAPL"]), 1))


def test_a_dropped_connection_reconnects() -> None:
    first = FakeSocket([CONNECTED, AUTHED, SUBSCRIBED, [_bar("AAPL", "2026-11-27T14:31:00Z")]])
    second = FakeSocket([CONNECTED, AUTHED, SUBSCRIBED, [_bar("AAPL", "2026-11-27T14:33:00Z")]])
    connect, urls = _connector(first, second)
    feed = _feed(connect)

    async def run() -> list:
        from stockviz.services.feeds import base

        original = base.asyncio.sleep

        async def no_wait(_seconds: float) -> None:
            await original(0)

        base.asyncio.sleep = no_wait  # type: ignore[assignment]
        try:
            return await _take(feed.stream(["AAPL"]), 2)
        finally:
            base.asyncio.sleep = original  # type: ignore[assignment]

    bars = asyncio.run(run())
    assert [b.ts.minute for b in bars] == [31, 33] and len(urls) == 2


def test_limits_and_refusals() -> None:
    connect, _ = _connector()
    feed = _feed(connect)
    with pytest.raises(ValueError, match="at most 30"):
        feed.stream([f"S{i}" for i in range(31)])
    with pytest.raises(NotSupported):
        AlpacaFeed(key="k", secret="s", feed="sip", connect=connect).stream(["AAPL"])
    with pytest.raises(ValueError):
        feed.stream(["TCS.NS"])  # US feeds never get an Indian symbol


def test_capabilities_say_it_streams() -> None:
    assert AlpacaFeed.capabilities.stream is True
