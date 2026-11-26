"""Alpaca market data v2: US minute-bar history (A6.3). Streaming is A6.6.

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

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from stockviz.services.feeds.base import (
    Capabilities,
    FeedBar,
    FeedProviderError,
    NotSupported,
    RateLimitSpec,
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
        stream=False,
        coverage=("iex", "sip"),
        symbols_limit=30,
        history_days=None,
        rate_limits=(RateLimitSpec(calls=200, per_seconds=60),),
        notes="Basic plan: live IEX only; SIP history at least 15 minutes old; since 2016.",
    )

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
