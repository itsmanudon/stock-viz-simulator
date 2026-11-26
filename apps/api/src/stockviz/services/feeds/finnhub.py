"""Finnhub (free): the backup WebSocket, a stub until A6.6 (A6.3).

**No history adapter.** Finnhub's stock candles (``/stock/candle``) are a
premium endpoint: a free-plan request answers "You don't have access to this
resource" (github.com/finnhubio/Finnhub-API issue 546; the Grafana Finnhub
data-source troubleshooting page says candles need a premium token). Finnhub's
own docs and pricing pages render only with JavaScript and could not be read
on 26 Nov 2026, so the free plan's limits (60 calls a minute and 50 WebSocket
symbols, from search-result text) stay unconfirmed. The stream (trades over
``wss://ws.finnhub.io``) is built with the live feed in A6.6, after its
message shapes are read from Finnhub's own page.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from stockviz.services.feeds.base import Capabilities, FeedBar, NotSupported
from stockviz.services.feeds.provider import HttpFeed

HISTORY_REASON = (
    "Finnhub's stock candles are premium-only, so the free plan gives no minute history"
)


@dataclass(repr=False)
class FinnhubFeed(HttpFeed):
    name = "finnhub"
    label = "Finnhub"
    capabilities = Capabilities(
        history=False,
        stream=False,
        coverage=(),
        notes="Backup WebSocket (A6.6). Free limits unconfirmed; candles are premium.",
    )

    def minute_bars(self, symbol: str, start: datetime, end: datetime) -> list[FeedBar]:
        raise NotSupported(self.label, HISTORY_REASON)
