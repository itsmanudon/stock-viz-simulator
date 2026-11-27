"""Alpaca market data v2: US minute-bar history (A6.3) and the live IEX stream (A6.6).

Stream (docs.alpaca.markets/docs/real-time-stock-pricing-data and
/streaming-market-data, read 27 Nov 2026): ``wss://stream.data.alpaca.markets/v2/iex``;
the server sends ``[{"T":"success","msg":"connected"}]``; the client sends
``{"action":"auth","key":...,"secret":...}`` within 10 seconds and gets
``[{"T":"success","msg":"authenticated"}]``; ``{"action":"subscribe","bars":[...]}``
is answered with the full ``{"T":"subscription",...}`` list. Every message is a
JSON array (data may be batched). A minute bar is ``{"T":"b","S","o","h","l",
"c","v","vw","n","t"}``, emitted just after the minute with that minute's
trades; ``t`` (RFC-3339) is the minute it covers, read as its open. Errors are
``{"T":"error","code","msg"}``: 401-404 auth, 405 symbol limit, 406
connection limit (most plans allow one), 407 slow client, 409 insufficient
subscription, 410 bad channel, 400 bad syntax, 500 internal. JSON text is the
default (msgpack is opt-in and not used).

Documented (docs.alpaca.markets, read 26 Nov 2026; see apps/api/CLAUDE.md):

- ``GET https://data.alpaca.markets/v2/stocks/{symbol}/bars`` with
  ``timeframe=1Min``, ``start``/``end`` (RFC-3339; ``end`` inclusive),
  ``limit`` (max 10,000), ``adjustment`` (``raw`` default; we ask
  ``split``, like the stored daily bars), ``feed`` (``iex`` | ``sip``),
  ``sort=asc`` and ``page_token`` (from ``next_page_token``).
- Headers ``APCA-API-KEY-ID`` and ``APCA-API-SECRET-KEY``.
- Response ``{"bars": [{"t", "o", "h", "l", "c", "v", "n", "vw"}],
  "symbol", "next_page_token"}``; ``t`` is RFC-3339 UTC, the bar's left
  edge (start). Minutes with no trade have no bar.
- Free (Basic) plan: IEX only for recent data, 200 calls a minute, history
  since 2016, and SIP history only when ``end`` is at least 15 minutes old.
  401 bad key, 403 not covered by the subscription, 429 rate limit.

The SIP rule is enforced here before any call: :class:`SipTooRecent`.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Literal, Protocol

from stockviz.services.feeds.base import (
    Capabilities,
    FeedAuthError,
    FeedBar,
    FeedNetworkError,
    FeedProviderError,
    FeedRateError,
    NotSupported,
    RateLimitSpec,
    Tick,
    reconnecting,
    us_symbol,
    utc,
)
from stockviz.services.feeds.http import get_json
from stockviz.services.feeds.normalise import iso_instant, make_bar, ohlcv
from stockviz.services.feeds.provider import HttpFeed

ALPACA_DATA_ROOT = "https://data.alpaca.markets"
PAGE_LIMIT = 10_000
MAX_PAGES = 1_000
SIP_DELAY = timedelta(minutes=15)
ADJUSTMENT = "split"

AlpacaFeedName = Literal["iex", "sip"]

STREAM_URL = "wss://stream.data.alpaca.markets/v2/iex"
STREAM_SYMBOL_LIMIT = 30
LIVE_SOURCE = "alpaca_iex_live"
AUTH_CODES = frozenset({401, 402, 403, 404})
RETRY_CODES = frozenset({407, 500})
CONNECTION_LIMIT_RETRY = 60.0


class StreamSocket(Protocol):
    """What the stream needs of a WebSocket connection (``websockets`` gives it)."""

    async def send(self, message: str) -> None: ...
    async def recv(self) -> str | bytes: ...


Connect = Callable[[str], Any]
"""``connect(url)`` -> an async context manager yielding a :class:`StreamSocket`."""


def _default_connect(url: str) -> Any:
    from websockets.asyncio.client import connect

    return connect(url, open_timeout=10, close_timeout=5, max_size=2**22)


def _stream_error(label: str, message: dict[str, Any]) -> Exception:
    raw = message.get("code")
    code = int(raw) if isinstance(raw, int | Decimal) and raw == int(raw) else None
    if code in AUTH_CODES:
        return FeedAuthError(label, "stream authentication failed", status=code)
    if code == 406:
        return FeedRateError(
            label, "stream connection limit reached", status=code,
            retry_after=CONNECTION_LIMIT_RETRY,
        )  # fmt: skip
    if code in RETRY_CODES:
        return FeedNetworkError(label, "stream dropped by the server", status=code)
    if code == 405:
        return FeedProviderError(label, "stream symbol limit reached", status=code)
    if code == 409:
        return FeedProviderError(label, "the IEX stream is not in this subscription", status=code)
    return FeedProviderError(label, "stream refused the request", status=code)


class SipTooRecent(NotSupported):
    """Free plans get SIP history only when the query ends >= 15 minutes ago."""


def alpaca_symbol(ticker: str) -> str:
    """``BRK-B`` (StockViz, Yahoo style) -> ``BRK.B`` (Alpaca's share-class dot)."""
    return us_symbol(ticker).replace("-", ".")


def sip_allowed(end: datetime, now: datetime) -> bool:
    return utc(now) - utc(end) >= SIP_DELAY


def _iso(value: datetime) -> str:
    return utc(value).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(repr=False)
class AlpacaFeed(HttpFeed):
    secret: str = ""
    feed: AlpacaFeedName = "iex"

    name = "alpaca"
    label = "Alpaca"
    capabilities = Capabilities(
        history=True,
        stream=True,
        coverage=("iex", "sip"),
        symbols_limit=30,
        history_days=None,
        rate_limits=(RateLimitSpec(calls=200, per_seconds=60),),
        notes="Basic plan: live IEX only; SIP history at least 15 minutes old; since 2016.",
    )
    connect: Connect | None = None
    """Tests inject a fake socket; ``None`` uses ``websockets``."""

    @property
    def configured(self) -> bool:
        return bool(self.key.strip() and self.secret.strip())

    @property
    def source(self) -> str:
        return f"alpaca_{self.feed}"

    def minute_bars(self, symbol: str, start: datetime, end: datetime) -> list[FeedBar]:
        key = self._require_key()
        start, end = utc(start), utc(end)
        if start >= end:
            return []
        if self.feed == "sip" and not sip_allowed(end, self.now()):
            raise SipTooRecent(
                self.label, "SIP history needs the query to end at least 15 minutes ago"
            )
        wire = alpaca_symbol(symbol)
        url = f"{ALPACA_DATA_ROOT}/v2/stocks/{wire}/bars"
        headers = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": self.secret.strip()}
        params = {
            "timeframe": "1Min",
            "start": _iso(start),
            # ``end`` is inclusive on Alpaca's side; the bar opening at
            # ``end`` is dropped below so the range is [start, end).
            "end": _iso(end),
            "limit": str(PAGE_LIMIT),
            "adjustment": ADJUSTMENT,
            "feed": self.feed,
            "sort": "asc",
        }
        bars: dict[datetime, FeedBar] = {}
        seen_tokens: set[str] = set()
        for _ in range(MAX_PAGES):
            body = get_json(
                self.label, url, params=params, headers=headers, limiter=self.limiter, get=self.get
            )
            if not isinstance(body, dict):
                raise FeedProviderError(self.label, "answered in an unexpected shape")
            rows = body.get("bars") or []
            if not isinstance(rows, list):
                raise FeedProviderError(self.label, "bars is not a list")
            for row in rows:
                if not isinstance(row, dict):
                    raise FeedProviderError(self.label, "bar is not an object")
                ts = iso_instant(self.label, row.get("t"))
                if not start <= ts < end:
                    continue
                o, h, lo, c, v = ohlcv(self.label, row, ("o", "h", "l", "c", "v"))
                bars[ts] = make_bar(
                    self.label,
                    symbol=us_symbol(symbol),
                    ts=ts,
                    open_=o,
                    high=h,
                    low=lo,
                    close=c,
                    volume=v,
                    feed=self.feed,
                    source=self.source,
                )
            token = body.get("next_page_token")
            if not token:
                return [bars[t] for t in sorted(bars)]
            if not isinstance(token, str) or token in seen_tokens:
                raise FeedProviderError(self.label, "pagination repeated a page")
            seen_tokens.add(token)
            params = {**params, "page_token": token}
        raise FeedProviderError(self.label, "too many pages")

    # --- live stream (A6.6) -----------------------------------------------------

    def stream(self, symbols: Sequence[str]) -> AsyncIterator[Tick | FeedBar]:
        """Live IEX minute bars for up to 30 US symbols, reconnecting after a
        dropped connection; a bad key or a refused subscription ends it."""
        key = self._require_key()
        if self.feed != "iex":
            raise NotSupported(self.label, "the free plan streams IEX only")
        wanted = sorted({us_symbol(s) for s in symbols})
        if not wanted:
            raise ValueError("no symbols to stream")
        if len(wanted) > STREAM_SYMBOL_LIMIT:
            raise ValueError(f"the IEX stream takes at most {STREAM_SYMBOL_LIMIT} symbols")
        return reconnecting(lambda: self._stream_once(wanted, key))

    async def _stream_once(self, symbols: list[str], key: str) -> AsyncIterator[FeedBar]:
        wire = {alpaca_symbol(s): s for s in symbols}
        connect = self.connect or _default_connect
        try:
            async with connect(STREAM_URL) as socket:
                await self._expect(socket, "connected")
                await socket.send(
                    json.dumps({"action": "auth", "key": key, "secret": self.secret.strip()})
                )
                await self._expect(socket, "authenticated")
                await socket.send(json.dumps({"action": "subscribe", "bars": sorted(wire)}))
                while True:
                    for message in await self._messages(socket):
                        kind = message.get("T")
                        if kind == "error":
                            raise _stream_error(self.label, message)
                        if kind == "b":
                            bar = self._stream_bar(message, wire)
                            if bar is not None:
                                yield bar
        except (FeedAuthError, FeedRateError, FeedNetworkError, FeedProviderError):
            raise
        except (OSError, TimeoutError, EOFError) as exc:
            raise FeedNetworkError(self.label, "stream connection lost") from exc
        except Exception as exc:  # websockets' ConnectionClosed and friends
            if type(exc).__module__.startswith("websockets"):
                raise FeedNetworkError(self.label, "stream connection lost") from exc
            raise

    async def _messages(self, socket: StreamSocket) -> list[dict[str, Any]]:
        raw = await socket.recv()
        try:
            body = json.loads(raw, parse_float=Decimal, parse_int=Decimal)
        except (ValueError, TypeError) as exc:
            raise FeedProviderError(self.label, "stream sent something that is not JSON") from exc
        if not isinstance(body, list) or not all(isinstance(m, dict) for m in body):
            raise FeedProviderError(self.label, "stream message is not an array of objects")
        return body

    async def _expect(self, socket: StreamSocket, msg: str) -> None:
        for message in await self._messages(socket):
            if message.get("T") == "error":
                raise _stream_error(self.label, message)
            if message.get("T") == "success" and message.get("msg") == msg:
                return
        raise FeedProviderError(self.label, f"stream did not say {msg}")

    def _stream_bar(self, message: dict[str, Any], wire: dict[str, str]) -> FeedBar | None:
        symbol = wire.get(str(message.get("S", "")))
        if symbol is None:
            return None  # not ours (a wildcard elsewhere); ignored
        ts = iso_instant(self.label, message.get("t"))
        o, h, lo, c, v = ohlcv(self.label, message, ("o", "h", "l", "c", "v"))
        return make_bar(
            self.label, symbol=symbol, ts=ts, open_=o, high=h, low=lo, close=c, volume=v,
            feed="iex", source=LIVE_SOURCE,
        )  # fmt: skip
