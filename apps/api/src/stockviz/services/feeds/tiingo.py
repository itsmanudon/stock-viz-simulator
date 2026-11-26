"""Tiingo: IEX intraday and end-of-day history (A6.3). No stream here.

Documented (tiingo.com/documentation, read 26 Nov 2026; see apps/api/CLAUDE.md):

- IEX intraday: ``GET https://api.tiingo.com/iex/<ticker>/prices`` with
  ``startDate``, ``resampleFreq`` (we send ``1min``) and ``columns``
  (``volume`` is only returned when named there, and is IEX-only volume).
  Rows ``{date, open, high, low, close, volume}``.
- End of day: ``GET https://api.tiingo.com/tiingo/daily/<ticker>/prices``
  with ``startDate``/``endDate``; rows ``{date, open, high, low, close,
  volume, adjOpen, adjHigh, adjLow, adjClose, adjVolume, divCash,
  splitFactor}``.
- Auth: header ``Authorization: Token <token>``.
- Free (Starter) plan: 50 requests an hour, 1,000 a day, 500 unique symbols
  a month, 1 GB a month; personal, internal use only.

**Not confirmed by the docs** (checked on the first real run, owner key):
``endDate`` on the IEX endpoint (documented on end of day), the ``date``
string's format and zone (parsed only with an explicit offset; a naive time
is refused), whether ``date`` is the bar's start (taken as its start, like
every other feed), row caps per request (queries go in ``CHUNK_DAYS``
chunks), error status codes and bodies (classified by status; a 200 whose
body is an object, not a list, is a provider error).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal

from stockviz.services.feeds.base import (
    Capabilities,
    FeedBar,
    FeedProviderError,
    RateLimitSpec,
    us_symbol,
    utc,
)
from stockviz.services.feeds.http import get_json
from stockviz.services.feeds.normalise import iso_instant, make_bar, number, ohlcv, whole_volume
from stockviz.services.feeds.provider import HttpFeed

TIINGO_ROOT = "https://api.tiingo.com"
CHUNK_DAYS = 5
"""Calendar days per IEX request (about 1,950 regular-hours minutes)."""
SOURCE = "tiingo_iex"


def tiingo_symbol(ticker: str) -> str:
    """``BRK-B`` -> ``brk-b``: Tiingo writes share classes with a hyphen."""
    return us_symbol(ticker).replace(".", "-").lower()


@dataclass(frozen=True, slots=True)
class TiingoDailyBar:
    symbol: str
    session_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    adj_close: Decimal
    div_cash: Decimal
    split_factor: Decimal


def chunks(start: date, end: date, days: int = CHUNK_DAYS) -> list[tuple[date, date]]:
    """Inclusive (first, last) calendar-day windows covering start..end."""
    out: list[tuple[date, date]] = []
    cursor = start
    while cursor <= end:
        last = min(end, cursor + timedelta(days=days - 1))
        out.append((cursor, last))
        cursor = last + timedelta(days=1)
    return out


@dataclass(repr=False)
class TiingoFeed(HttpFeed):
    name = "tiingo"
    label = "Tiingo"
    capabilities = Capabilities(
        history=True,
        stream=False,
        coverage=("iex",),
        rate_limits=(
            RateLimitSpec(calls=50, per_seconds=3600),
            RateLimitSpec(calls=1000, per_seconds=86400),
        ),
        notes="Starter plan: 50 requests an hour, 1,000 a day, 500 symbols a month.",
    )

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Token {self._require_key()}", "Content-Type": "application/json"}

    def _rows(self, url: str, params: dict[str, str]) -> list[dict[str, object]]:
        body = get_json(
            self.label,
            url,
            params=params,
            headers=self._headers(),
            limiter=self.limiter,
            get=self.get,
        )
        if not isinstance(body, list):
            raise FeedProviderError(self.label, "answered with an error object, not rows")
        if not all(isinstance(row, dict) for row in body):
            raise FeedProviderError(self.label, "bar is not an object")
        return body

    def minute_bars(self, symbol: str, start: datetime, end: datetime) -> list[FeedBar]:
        self._require_key()
        start, end = utc(start), utc(end)
        if start >= end:
            return []
        url = f"{TIINGO_ROOT}/iex/{tiingo_symbol(symbol)}/prices"
        last_day = (end - timedelta(microseconds=1)).date()
        bars: dict[datetime, FeedBar] = {}
        for first, last in chunks(start.date(), last_day):
            params = {
                "startDate": first.isoformat(),
                "endDate": last.isoformat(),
                "resampleFreq": "1min",
                "columns": "open,high,low,close,volume",
            }
            for row in self._rows(url, params):
                ts = iso_instant(self.label, row.get("date"))
                if not start <= ts < end:
                    continue
                o, h, lo, c, v = ohlcv(self.label, row, ("open", "high", "low", "close", "volume"))
                bars[ts] = make_bar(
                    self.label,
                    symbol=us_symbol(symbol),
                    ts=ts,
                    open_=o,
                    high=h,
                    low=lo,
                    close=c,
                    volume=v,
                    feed="iex",
                    source=SOURCE,
                )
        return [bars[t] for t in sorted(bars)]

    def daily_bars(self, symbol: str, start: date, end: date) -> list[TiingoDailyBar]:
        """End-of-day history (not stored by this batch; a second daily source)."""
        self._require_key()
        url = f"{TIINGO_ROOT}/tiingo/daily/{tiingo_symbol(symbol)}/prices"
        rows = self._rows(url, {"startDate": start.isoformat(), "endDate": end.isoformat()})
        out: list[TiingoDailyBar] = []
        for row in rows:
            raw = row.get("date")
            try:
                day = date.fromisoformat(str(raw)[:10])
            except ValueError:
                raise FeedProviderError(self.label, "bar has a malformed date") from None
            o, h, lo, c, v = ohlcv(self.label, row, ("open", "high", "low", "close", "volume"))
            if min(o, h, lo, c) <= 0 or h < max(o, c, lo) or lo > min(o, c, h):
                raise FeedProviderError(self.label, "bar has an impossible price")
            out.append(
                TiingoDailyBar(
                    symbol=us_symbol(symbol),
                    session_date=day,
                    open=o,
                    high=h,
                    low=lo,
                    close=c,
                    volume=whole_volume(self.label, v),
                    adj_close=number(self.label, row, "adjClose"),
                    div_cash=number(self.label, row, "divCash"),
                    split_factor=number(self.label, row, "splitFactor"),
                )
            )
        out.sort(key=lambda b: b.session_date)
        return out
