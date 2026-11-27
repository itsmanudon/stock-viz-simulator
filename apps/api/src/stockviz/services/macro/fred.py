"""The FRED client (A9.7, M1.10).

Two documented endpoints (https://fred.stlouisfed.org/docs/api/fred/, read
27 Nov 2026):

- ``GET https://api.stlouisfed.org/fred/series`` with ``series_id``,
  ``api_key``, ``file_type=json`` -> ``{"seriess": [{id, title, units,
  frequency, observation_start, observation_end, last_updated, ...}]}``.
- ``GET https://api.stlouisfed.org/fred/series/observations`` with the same
  and ``observation_start=YYYY-MM-DD`` -> ``{"observations": [{date, value},
  ...]}``, oldest first. A value of ``"."`` is a date without a number.

The key travels as a query parameter, which ``get_json`` never puts in an
error message. FRED allows 120 requests a minute; the limiter keeps under it.
Tests answer from hand-written fixtures; no test reaches FRED.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from stockviz.services.feeds.base import FeedNotConfigured, FeedProviderError, RateLimitSpec
from stockviz.services.feeds.http import HttpGet, default_get, get_json
from stockviz.services.feeds.ratelimit import RateLimiter

BASE = "https://api.stlouisfed.org/fred"
LABEL = "FRED"
RATE_LIMITS = (RateLimitSpec(calls=100, per_seconds=60),)


@dataclass(frozen=True)
class SeriesMeta:
    series_id: str
    title: str
    units: str
    frequency: str
    observation_start: date | None
    observation_end: date | None
    last_updated: str | None


def _date(raw: object) -> date | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


def _value(raw: object) -> Decimal | None:
    if raw is None or raw == ".":
        return None
    try:
        value = Decimal(str(raw))
    except InvalidOperation as exc:
        raise FeedProviderError(LABEL, "observation value is not a number") from exc
    return value if value.is_finite() else None


class FredClient:
    def __init__(
        self,
        api_key: str,
        *,
        get: HttpGet = default_get,
        limiter: RateLimiter | None = None,
    ) -> None:
        self._key = api_key
        self.get = get
        self.limiter = limiter or RateLimiter.from_specs(RATE_LIMITS)

    def _call(self, path: str, params: dict[str, str]) -> Any:
        if not self._key:
            raise FeedNotConfigured("FRED_API_KEY is not set")
        body = get_json(
            LABEL,
            f"{BASE}/{path}",
            params={**params, "api_key": self._key, "file_type": "json"},
            headers={},
            limiter=self.limiter,
            get=self.get,
        )
        if not isinstance(body, dict):
            raise FeedProviderError(LABEL, "answered with something other than an object")
        return body

    def series(self, series_id: str) -> SeriesMeta:
        body = self._call("series", {"series_id": series_id})
        rows = body.get("seriess")
        if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
            raise FeedProviderError(LABEL, "series metadata missing")
        row = rows[0]
        return SeriesMeta(
            series_id=str(row.get("id") or series_id),
            title=str(row.get("title") or series_id)[:300],
            units=str(row.get("units") or "")[:120],
            frequency=str(row.get("frequency") or "")[:40],
            observation_start=_date(row.get("observation_start")),
            observation_end=_date(row.get("observation_end")),
            last_updated=(str(row["last_updated"])[:40] if row.get("last_updated") else None),
        )

    def observations(self, series_id: str, start: date) -> list[tuple[date, Decimal | None]]:
        body = self._call(
            "series/observations",
            {"series_id": series_id, "observation_start": start.isoformat()},
        )
        rows = body.get("observations")
        if not isinstance(rows, list):
            raise FeedProviderError(LABEL, "observations missing")
        out: list[tuple[date, Decimal | None]] = []
        for row in rows:
            if not isinstance(row, dict):
                raise FeedProviderError(LABEL, "observation is not an object")
            day = _date(row.get("date"))
            if day is None:
                raise FeedProviderError(LABEL, "observation date is unreadable")
            out.append((day, _value(row.get("value"))))
        return out
