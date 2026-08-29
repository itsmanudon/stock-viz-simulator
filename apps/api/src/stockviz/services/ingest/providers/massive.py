"""Private Massive REST adapter for US daily-bar shadow comparisons.

Massive wire names, URLs, pagination, request IDs, and corporate-action IDs
stop in this module. Daily aggregates leave it only as canonical ``BarRecord``
objects; no function here persists or serves provider data.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

import httpx

from stockviz.services.ingest.bar_semantics import (
    AdjustmentSemantics,
    SessionScope,
    new_york_session_date,
    session_label,
)
from stockviz.services.ingest.prices import DAILY_INTERVAL, BarRecord

MASSIVE_API_ROOT = "https://api.massive.com"
SOURCE_MASSIVE = "massive"

MassiveGetFn = Callable[[str, dict[str, str], dict[str, str]], dict[str, Any]]


class MassiveProviderError(RuntimeError):
    """Massive rejected or could not fulfill a request."""


class MassiveSemanticError(ValueError):
    """A response cannot be mapped to StockViz's canonical semantics."""


@dataclass(frozen=True, slots=True)
class MassiveAction:
    """Provider-private corporate-action representation."""

    kind: str
    ticker: str
    effective_date: date
    provider_id: str
    split_from: Decimal | None = None
    split_to: Decimal | None = None
    cash_amount: Decimal | None = None
    currency: str | None = None


@dataclass(frozen=True, slots=True)
class MassiveOpenClose:
    """Provider-private per-date probe used to audit daily session scope."""

    ticker: str
    session_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    pre_market: Decimal | None
    after_hours: Decimal | None


def _default_get(
    url: str,
    params: dict[str, str],
    headers: dict[str, str],
) -> dict[str, Any]:
    """Fetch one page while preserving every JSON number as ``Decimal``."""

    response = httpx.get(url, params=params, headers=headers, timeout=30.0)
    response.raise_for_status()
    try:
        payload = json.loads(response.content, parse_float=Decimal, parse_int=Decimal)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise MassiveProviderError("Massive returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise MassiveSemanticError("Massive response root must be an object")
    return payload


def _credential(api_key: str) -> str:
    value = api_key.strip()
    if not value:
        raise ValueError("MASSIVE_API_KEY is required for Massive shadow execution")
    return value


def _ticker(value: str) -> str:
    ticker = value.strip().upper()
    if not ticker:
        raise ValueError("ticker must not be blank")
    return ticker


def _date_range(start: date, end: date) -> None:
    if start > end:
        raise ValueError("start must be on or before end")


def _headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {_credential(api_key)}"}


def _provider_message(payload: Mapping[str, Any]) -> str:
    for key in ("error", "message"):
        value = payload.get(key)
        if value:
            return str(value)
    return "unspecified provider error"


def _validate_status(payload: Mapping[str, Any]) -> None:
    status = str(payload.get("status", "")).strip().upper()
    if status == "OK":
        return
    if status == "ERROR":
        raise MassiveProviderError(f"Massive provider error: {_provider_message(payload)}")
    if not status:
        raise MassiveSemanticError("Massive response is missing status")
    raise MassiveProviderError(f"Massive returned status {status}: {_provider_message(payload)}")


def _call_get(
    get_fn: MassiveGetFn,
    url: str,
    params: dict[str, str],
    headers: dict[str, str],
) -> dict[str, Any]:
    try:
        payload = get_fn(url, params, headers)
    except httpx.HTTPStatusError as exc:
        raise MassiveProviderError(f"Massive HTTP {exc.response.status_code}") from exc
    except httpx.RequestError as exc:
        raise MassiveProviderError(f"Massive request failed: {exc}") from exc
    if not isinstance(payload, dict):
        raise MassiveSemanticError("Massive response root must be an object")
    _validate_status(payload)
    return payload


def _sanitize_next_url(raw: object) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise MassiveSemanticError("Massive next_url must be a non-empty URL")
    parts = urlsplit(raw)
    if parts.scheme.lower() != "https" or parts.hostname != "api.massive.com":
        raise MassiveSemanticError("Massive next_url must remain on https://api.massive.com")
    query = urlencode(
        [(key, value) for key, value in parse_qsl(parts.query) if key.lower() != "apikey"]
    )
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, ""))


def _pages(
    url: str,
    *,
    params: dict[str, str],
    api_key: str,
    get_fn: MassiveGetFn,
) -> Iterator[dict[str, Any]]:
    headers = _headers(api_key)
    seen: set[str] = set()
    current_url = url
    current_params = params
    while True:
        if current_url in seen:
            raise MassiveSemanticError("Massive pagination repeated next_url")
        seen.add(current_url)
        payload = _call_get(get_fn, current_url, current_params, headers)
        yield payload
        next_url = payload.get("next_url")
        if not next_url:
            return
        current_url = _sanitize_next_url(next_url)
        current_params = {}


def _decimal(value: object, *, field: str) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise MassiveSemanticError(f"Massive malformed numeric field {field}")
    try:
        parsed = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise MassiveSemanticError(f"Massive malformed numeric field {field}") from exc
    if not parsed.is_finite():
        raise MassiveSemanticError(f"Massive malformed numeric field {field}")
    return parsed


def _row_decimal(row: Mapping[str, Any], key: str) -> Decimal:
    if key not in row:
        raise MassiveSemanticError(f"Massive malformed aggregate row: missing {key}")
    return _decimal(row[key], field=key)


def _row_date(row: Mapping[str, Any], key: str) -> date:
    raw = row.get(key)
    if not isinstance(raw, str):
        raise MassiveSemanticError(f"Massive malformed date field {key}")
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise MassiveSemanticError(f"Massive malformed date field {key}") from exc


def _results(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    raw = payload.get("results", [])
    if not isinstance(raw, list):
        raise MassiveSemanticError("Massive results must be a list")
    if not all(isinstance(row, Mapping) for row in raw):
        raise MassiveSemanticError("Massive results contain a malformed row")
    return raw


def _validate_ohlcv(
    *,
    open_: Decimal,
    high: Decimal,
    low: Decimal,
    close: Decimal,
    volume: Decimal,
) -> None:
    if any(value < 0 for value in (open_, high, low, close)):
        raise MassiveSemanticError("Massive OHLC values must be non-negative")
    if volume < 0:
        raise MassiveSemanticError("Massive volume must be non-negative")
    if high < max(open_, close, low) or low > min(open_, close, high):
        raise MassiveSemanticError("Massive malformed OHLC range")


def fetch_massive_daily(
    ticker: str,
    *,
    start: date,
    end: date,
    api_key: str,
    get_fn: MassiveGetFn = _default_get,
) -> list[BarRecord]:
    """Fetch split-adjusted Massive daily aggregates as canonical bars."""

    symbol = _ticker(ticker)
    _date_range(start, end)
    url = (
        f"{MASSIVE_API_ROOT}/v2/aggs/ticker/{quote(symbol, safe='.')}/range/1/day/"
        f"{start.isoformat()}/{end.isoformat()}"
    )
    params = {"adjusted": "true", "sort": "asc", "limit": "50000"}
    bars: list[BarRecord] = []
    seen_sessions: set[date] = set()
    for payload in _pages(url, params=params, api_key=api_key, get_fn=get_fn):
        if payload.get("adjusted") is not True:
            raise MassiveSemanticError("Massive aggregates response must be adjusted=true")
        for row in _results(payload):
            open_ = _row_decimal(row, "o")
            high = _row_decimal(row, "h")
            low = _row_decimal(row, "l")
            close = _row_decimal(row, "c")
            volume = _row_decimal(row, "v")
            millis = _row_decimal(row, "t")
            if millis != millis.to_integral_value():
                raise MassiveSemanticError("Massive aggregate timestamp must be integer milliseconds")
            instant = datetime(1970, 1, 1, tzinfo=UTC) + timedelta(milliseconds=int(millis))
            session_date = new_york_session_date(instant)
            if session_date in seen_sessions:
                raise MassiveSemanticError(
                    f"Massive aggregates contain duplicate session {session_date.isoformat()}"
                )
            _validate_ohlcv(open_=open_, high=high, low=low, close=close, volume=volume)
            seen_sessions.add(session_date)
            bars.append(
                BarRecord(
                    ticker=symbol,
                    ts=session_label(session_date),
                    interval=DAILY_INTERVAL,
                    open=open_,
                    high=high,
                    low=low,
                    close=close,
                    volume=volume,
                    source=SOURCE_MASSIVE,
                    adjustment_semantics=AdjustmentSemantics.SPLIT_ADJUSTED,
                    session_scope=SessionScope.PROVIDER_DAILY,
                )
            )
    bars.sort(key=lambda bar: bar.ts)
    return bars


def _fetch_actions(
    ticker: str,
    *,
    start: date,
    end: date,
    api_key: str,
    kind: str,
    date_field: str,
    get_fn: MassiveGetFn,
) -> list[MassiveAction]:
    symbol = _ticker(ticker)
    _date_range(start, end)
    url = f"{MASSIVE_API_ROOT}/stocks/v1/{kind}s"
    params = {
        "ticker": symbol,
        f"{date_field}.gte": start.isoformat(),
        f"{date_field}.lte": end.isoformat(),
        "sort": date_field,
        "order": "asc",
        "limit": "1000",
    }
    actions: list[MassiveAction] = []
    for payload in _pages(url, params=params, api_key=api_key, get_fn=get_fn):
        for row in _results(payload):
            provider_id = row.get("id")
            if not isinstance(provider_id, str) or not provider_id:
                raise MassiveSemanticError(f"Massive malformed {kind} id")
            effective_date = _row_date(row, date_field)
            if kind == "split":
                split_from = _row_decimal(row, "split_from")
                split_to = _row_decimal(row, "split_to")
                if split_from <= 0 or split_to <= 0:
                    raise MassiveSemanticError("Massive split ratio must be positive")
                actions.append(
                    MassiveAction(
                        kind=kind,
                        ticker=symbol,
                        effective_date=effective_date,
                        provider_id=provider_id,
                        split_from=split_from,
                        split_to=split_to,
                    )
                )
                continue
            cash_amount = _row_decimal(row, "cash_amount")
            if cash_amount < 0:
                raise MassiveSemanticError("Massive dividend cash amount must be non-negative")
            currency = row.get("currency")
            actions.append(
                MassiveAction(
                    kind=kind,
                    ticker=symbol,
                    effective_date=effective_date,
                    provider_id=provider_id,
                    cash_amount=cash_amount,
                    currency=str(currency).upper() if currency else None,
                )
            )
    return actions


def fetch_massive_splits(
    ticker: str,
    *,
    start: date,
    end: date,
    api_key: str,
    get_fn: MassiveGetFn = _default_get,
) -> list[MassiveAction]:
    return _fetch_actions(
        ticker,
        start=start,
        end=end,
        api_key=api_key,
        kind="split",
        date_field="execution_date",
        get_fn=get_fn,
    )


def fetch_massive_dividends(
    ticker: str,
    *,
    start: date,
    end: date,
    api_key: str,
    get_fn: MassiveGetFn = _default_get,
) -> list[MassiveAction]:
    return _fetch_actions(
        ticker,
        start=start,
        end=end,
        api_key=api_key,
        kind="dividend",
        date_field="ex_dividend_date",
        get_fn=get_fn,
    )


def fetch_massive_open_close(
    ticker: str,
    *,
    session_date: date,
    api_key: str,
    get_fn: MassiveGetFn = _default_get,
) -> MassiveOpenClose:
    symbol = _ticker(ticker)
    url = (
        f"{MASSIVE_API_ROOT}/v1/open-close/{quote(symbol, safe='.')}/"
        f"{session_date.isoformat()}"
    )
    payload = _call_get(get_fn, url, {"adjusted": "true"}, _headers(api_key))
    response_date = payload.get("from")
    if response_date != session_date.isoformat():
        raise MassiveSemanticError("Massive open-close response date does not match request")
    open_ = _decimal(payload.get("open"), field="open")
    high = _decimal(payload.get("high"), field="high")
    low = _decimal(payload.get("low"), field="low")
    close = _decimal(payload.get("close"), field="close")
    volume = _decimal(payload.get("volume"), field="volume")
    _validate_ohlcv(open_=open_, high=high, low=low, close=close, volume=volume)
    pre_market_raw = payload.get("preMarket")
    after_hours_raw = payload.get("afterHours")
    return MassiveOpenClose(
        ticker=symbol,
        session_date=session_date,
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=volume,
        pre_market=(
            _decimal(pre_market_raw, field="preMarket") if pre_market_raw is not None else None
        ),
        after_hours=(
            _decimal(after_hours_raw, field="afterHours")
            if after_hours_raw is not None
            else None
        ),
    )
