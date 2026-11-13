"""Kite Connect (Zerodha) adapter for NSE and BSE daily history (Phase 4.7).

Optional. Kite wire names, URLs and tokens stop in this module; bars leave
it as canonical ``BarRecord`` objects with source ``kite``.

Kite access tokens expire every day and need a manual login on Zerodha's own
page (an exchange rule; never automate it). So Kite is a **snapshot**
provider: the owner logs in, copies the one-time ``request_token`` from the
redirect address, and runs ``stockviz.cli ingest-history --provider kite``.
That command swaps the request token for the day's access token in memory,
pulls full history, and never stores the token. Nightly prices stay on
yfinance; a stored Kite bar outranks it (``prices.SOURCE_RANK``).

Wire format: Kite Connect v3 (``X-Kite-Version: 3``):

- login: ``https://kite.zerodha.com/connect/login?v=3&api_key=...``
- session: ``POST /session/token`` with ``api_key``, ``request_token`` and
  ``checksum = sha256(api_key + request_token + api_secret)``
- instruments: ``GET /instruments/{exchange}`` (CSV)
- daily candles: ``GET /instruments/historical/{token}/day?from=&to=``, at
  most 2000 days per request, rows ``[ts, open, high, low, close, volume]``
"""

from __future__ import annotations

import csv
import hashlib
import io
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx

from stockviz.services.ingest.bar_semantics import (
    AdjustmentSemantics,
    SessionScope,
    session_label,
)
from stockviz.services.ingest.prices import DAILY_INTERVAL, SOURCE_KITE, BarRecord

KITE_API_ROOT = "https://api.kite.trade"
KITE_LOGIN_URL = "https://kite.zerodha.com/connect/login"
MAX_DAYS_PER_REQUEST = 2000
KITE_EPOCH = date(2000, 1, 1)
"""Earliest day requested. Kite returns what it has after this."""

# Kite's equity daily candles are taken as split-adjusted, like yfinance's.
# ``ingest-history`` compares them with stored bars before any write, so a
# different basis shows up as a ratio jump in the dry run, not in the data.
KITE_ADJUSTMENT = AdjustmentSemantics.SPLIT_ADJUSTED

SUFFIX_EXCHANGE = {".NS": "NSE", ".BO": "BSE"}

KiteGetFn = Callable[[str, dict[str, str], dict[str, str]], httpx.Response]
KitePostFn = Callable[[str, dict[str, str], dict[str, str]], httpx.Response]


class KiteError(RuntimeError):
    """Kite refused a request or answered in an unexpected shape."""


def login_url(api_key: str) -> str:
    return f"{KITE_LOGIN_URL}?v=3&api_key={api_key}"


def session_checksum(api_key: str, request_token: str, api_secret: str) -> str:
    return hashlib.sha256(f"{api_key}{request_token}{api_secret}".encode()).hexdigest()


def kite_symbol(ticker: str) -> tuple[str, str] | None:
    """``RELIANCE.NS`` -> (``NSE``, ``RELIANCE``); None for a non-Indian ticker."""
    for suffix, exchange in SUFFIX_EXCHANGE.items():
        if ticker.upper().endswith(suffix):
            return exchange, ticker[: -len(suffix)].upper()
    return None


def _default_get(url: str, params: dict[str, str], headers: dict[str, str]) -> httpx.Response:
    return httpx.get(url, params=params, headers=headers, timeout=30.0)


def _default_post(url: str, data: dict[str, str], headers: dict[str, str]) -> httpx.Response:
    return httpx.post(url, data=data, headers=headers, timeout=30.0)


def _json(response: httpx.Response) -> Any:
    try:
        body = response.json()
    except ValueError as exc:
        raise KiteError(f"Kite answered {response.status_code} without JSON") from exc
    if response.status_code != 200 or body.get("status") != "success":
        # Kite's error bodies carry ``error_type`` and ``message``, never the token.
        raise KiteError(
            f"Kite {response.status_code}: {body.get('error_type')}: {body.get('message')}"
        )
    return body["data"]


@dataclass
class KiteClient:
    api_key: str
    access_token: str
    get: KiteGetFn = _default_get

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "X-Kite-Version": "3",
            "Authorization": f"token {self.api_key}:{self.access_token}",
        }

    def instrument_tokens(self, exchange: str) -> dict[str, int]:
        """Trading symbol -> instrument token for equities on ``exchange``."""
        response = self.get(f"{KITE_API_ROOT}/instruments/{exchange}", {}, self._headers)
        if response.status_code != 200:
            raise KiteError(f"Kite instruments {exchange}: HTTP {response.status_code}")
        out: dict[str, int] = {}
        for row in csv.DictReader(io.StringIO(response.text)):
            if row.get("instrument_type") in ("EQ", None) and row.get("segment") == exchange:
                out[row["tradingsymbol"].upper()] = int(row["instrument_token"])
        return out

    def daily_bars(
        self, ticker: str, token: int, *, start: date = KITE_EPOCH, end: date
    ) -> list[BarRecord]:
        """Every daily candle from ``start`` to ``end``, in 2000-day requests."""
        bars: list[BarRecord] = []
        cursor = start
        while cursor <= end:
            stop = min(end, cursor + timedelta(days=MAX_DAYS_PER_REQUEST - 1))
            data = _json(
                self.get(
                    f"{KITE_API_ROOT}/instruments/historical/{token}/day",
                    {"from": cursor.isoformat(), "to": stop.isoformat()},
                    self._headers,
                )
            )
            bars.extend(_candle(ticker, row) for row in data.get("candles", []))
            cursor = stop + timedelta(days=1)
        return bars


def open_session(
    api_key: str,
    api_secret: str,
    request_token: str,
    *,
    post: KitePostFn = _default_post,
    get: KiteGetFn = _default_get,
) -> KiteClient:
    """Swap a one-time request token for today's access token (kept in memory)."""
    data = _json(
        post(
            f"{KITE_API_ROOT}/session/token",
            {
                "api_key": api_key,
                "request_token": request_token,
                "checksum": session_checksum(api_key, request_token, api_secret),
            },
            {"X-Kite-Version": "3"},
        )
    )
    return KiteClient(api_key=api_key, access_token=data["access_token"], get=get)


def _candle(ticker: str, row: list[Any]) -> BarRecord:
    # "2024-01-02T00:00:00+0530": the venue's own date, as for yfinance (4.1b).
    stamp = datetime.strptime(str(row[0]), "%Y-%m-%dT%H:%M:%S%z")
    open_, high, low, close = (Decimal(str(v)) for v in row[1:5])
    return BarRecord(
        ticker=ticker,
        ts=session_label(stamp.date()),
        interval=DAILY_INTERVAL,
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=Decimal(int(row[5])),
        source=SOURCE_KITE,
        adjustment_semantics=KITE_ADJUSTMENT,
        session_scope=SessionScope.REGULAR,
    )
