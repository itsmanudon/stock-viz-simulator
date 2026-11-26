"""Shared parsing for the adapters: numbers, instants, OHLCV checks (A6.3).

A malformed row is a :class:`FeedProviderError` with the field's name only,
never its value.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation

from stockviz.services.feeds.base import FeedBar, FeedProviderError, FeedTag


def number(provider: str, row: Mapping[str, object], key: str) -> Decimal:
    raw = row.get(key)
    if raw is None or isinstance(raw, bool):
        raise FeedProviderError(provider, f"bar is missing {key}")
    try:
        value = raw if isinstance(raw, Decimal) else Decimal(str(raw))
    except (InvalidOperation, ValueError):
        raise FeedProviderError(provider, f"bar has a malformed {key}") from None
    if not value.is_finite():
        raise FeedProviderError(provider, f"bar has a malformed {key}")
    return value


def iso_instant(provider: str, raw: object) -> datetime:
    """An RFC-3339 / ISO-8601 instant with an offset (``Z`` included) as aware UTC.

    A time without an offset is refused, never guessed.
    """
    if not isinstance(raw, str) or not raw.strip():
        raise FeedProviderError(provider, "bar has no timestamp")
    text = raw.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    # Nanosecond precision (Alpaca) is more than fromisoformat takes.
    if "." in text:
        head, _, rest = text.partition(".")
        digits = len(rest) - len(rest.lstrip("0123456789"))
        text = f"{head}.{rest[:digits][:6]}{rest[digits:]}"
    try:
        value = datetime.fromisoformat(text)
    except ValueError:
        raise FeedProviderError(provider, "bar has a malformed timestamp") from None
    if value.tzinfo is None:
        raise FeedProviderError(provider, "bar timestamp has no time zone")
    return value.astimezone(UTC)


def epoch_millis(provider: str, raw: Decimal) -> datetime:
    if raw != raw.to_integral_value():
        raise FeedProviderError(provider, "bar timestamp is not whole milliseconds")
    return datetime(1970, 1, 1, tzinfo=UTC) + timedelta(milliseconds=int(raw))


def whole_volume(provider: str, value: Decimal) -> int:
    """Share volume as an integer; a fractional count is rounded half up."""
    if value < 0:
        raise FeedProviderError(provider, "bar has a negative volume")
    return int(value.to_integral_value())


def make_bar(
    provider: str,
    *,
    symbol: str,
    ts: datetime,
    open_: Decimal,
    high: Decimal,
    low: Decimal,
    close: Decimal,
    volume: Decimal,
    feed: FeedTag,
    source: str,
) -> FeedBar:
    if min(open_, high, low, close) <= 0:
        raise FeedProviderError(provider, "bar has a non-positive price")
    if high < max(open_, close, low) or low > min(open_, close, high):
        raise FeedProviderError(provider, "bar has an impossible high or low")
    if ts.second or ts.microsecond:
        raise FeedProviderError(provider, "bar does not open on a minute")
    return FeedBar(
        symbol=symbol,
        ts=ts,
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=whole_volume(provider, volume),
        feed=feed,
        source=source,
    )


def ohlcv(provider: str, row: Mapping[str, object], keys: tuple[str, str, str, str, str]):
    o, h, lo, c, v = keys
    return (
        number(provider, row, o),
        number(provider, row, h),
        number(provider, row, lo),
        number(provider, row, c),
        number(provider, row, v),
    )
