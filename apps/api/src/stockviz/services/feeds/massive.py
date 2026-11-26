"""Massive (free Basic): US minute-history backfill (A6.3). No stream on the plan.

Reuses the existing shadow adapter's request, pagination and parsing
(``services/ingest/providers/massive.py::fetch_massive_minute_range``):
``GET https://api.massive.com/v2/aggs/ticker/{T}/range/1/minute/{from}/{to}``
with ``adjusted=true``, ``sort=asc``, ``limit=50000`` (base aggregates),
``next_url`` paging, ``Authorization: Bearer <key>``. Rows ``{o, h, l, c,
v, vw, n, t}``, ``t`` Unix milliseconds at the window's start; aggregates
include pre- and after-market minutes (we keep regular hours).

Massive aggregates are built from all US exchanges' qualifying trades, so
their bars carry feed ``sip``. Basic (massive.com/pricing and the
custom-bars page, read 26 Nov 2026): 5 calls a minute, 2 years of history,
end-of-day plan, no WebSockets. Undocumented on the pages read: the error
status codes and bodies (classified by HTTP status; the shadow adapter's
messages, which may hold Massive's text, are replaced by fixed ones).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from stockviz.services.feeds.base import (
    Capabilities,
    FeedBar,
    FeedError,
    FeedProviderError,
    RateLimitSpec,
    us_symbol,
    utc,
)
from stockviz.services.feeds.http import get_json
from stockviz.services.feeds.normalise import make_bar
from stockviz.services.feeds.provider import HttpFeed
from stockviz.services.feeds.tiingo import chunks
from stockviz.services.ingest.bar_semantics import NEW_YORK
from stockviz.services.ingest.providers.massive import (
    MassiveProviderError,
    MassiveSemanticError,
    fetch_massive_minute_range,
)

CHUNK_DAYS = 30
"""Calendar days per request: about 21 sessions x 960 minutes < 50,000 base aggregates."""
HISTORY_DAYS = 730
SOURCE = "massive"


def massive_symbol(ticker: str) -> str:
    return us_symbol(ticker).replace("-", ".")


@dataclass(repr=False)
class MassiveFeed(HttpFeed):
    name = "massive"
    label = "Massive"
    capabilities = Capabilities(
        history=True,
        stream=False,
        coverage=("sip",),
        history_days=HISTORY_DAYS,
        rate_limits=(RateLimitSpec(calls=5, per_seconds=60),),
        notes="Basic plan: 5 calls a minute, 2 years of minute aggregates, no WebSocket.",
    )

    def _get_fn(self, url: str, params: dict[str, str], headers: dict[str, str]) -> dict[str, Any]:
        body = get_json(
            self.label, url, params=params, headers=headers, limiter=self.limiter, get=self.get
        )
        if not isinstance(body, dict):
            raise FeedProviderError(self.label, "answered in an unexpected shape")
        return body

    def minute_bars(self, symbol: str, start: datetime, end: datetime) -> list[FeedBar]:
        key = self._require_key()
        start, end = utc(start), utc(end)
        if start >= end:
            return []
        first = start.astimezone(NEW_YORK).date()
        last = (end - timedelta(microseconds=1)).astimezone(NEW_YORK).date()
        out: dict[datetime, FeedBar] = {}
        for lo, hi in chunks(first, last, CHUNK_DAYS):
            try:
                rows = fetch_massive_minute_range(
                    massive_symbol(symbol), start=lo, end=hi, api_key=key, get_fn=self._get_fn
                )
            except FeedError:
                raise
            except (MassiveProviderError, MassiveSemanticError):
                # Their text may quote Massive's message; keep a fixed one.
                raise FeedProviderError(
                    self.label, "answered outside the documented shape"
                ) from None
            for row in rows:
                ts = utc(row.observed_at)
                if not start <= ts < end:
                    continue
                out[ts] = make_bar(
                    self.label,
                    symbol=us_symbol(symbol),
                    ts=ts,
                    open_=row.open,
                    high=row.high,
                    low=row.low,
                    close=row.close,
                    volume=row.volume,
                    feed="sip",
                    source=SOURCE,
                )
        return [out[t] for t in sorted(out)]


def history_floor(today: date) -> date:
    """The oldest date the Basic plan serves (2 years)."""
    return today - timedelta(days=HISTORY_DAYS)
