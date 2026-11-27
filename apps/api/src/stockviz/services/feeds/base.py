"""The feed and broker interfaces (A6.3, M1.6): workspace ``docs/a6-design-note.md``.

Two small protocols, so a data feed need not be a broker:

- :class:`FeedProvider`: market data. ``minute_bars`` (history: normalised
  one-minute bars, each tagged with its feed) and ``stream`` (an async
  iterator of ticks or bars, wrapped by :func:`reconnecting` for backoff).
  ``capabilities`` says what the provider can do; ``configured`` whether
  its key is set on this server.
- :class:`BrokerProvider`: login, fills import and basket export. Every
  method answers :class:`NotSupported` rather than raising, until A6.11
  builds the CSV maps and the Kite basket form.

Provider errors are classified (:class:`FeedError` and its ``kind``:
``auth``, ``rate``, ``network``, ``provider``) and carry a **fixed** message:
never the key, the URL with its query, or the provider's body text. The
backfill writes that fixed message to ``job_runs`` and the feed status
(``/v1/broker/feeds``) reads it back.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Literal, Protocol, runtime_checkable

from stockviz.services.markets.calendar import NEW_YORK_VENUE, venue_for_ticker

FeedTag = Literal["iex", "sip", "kite", "file", "replayed"]
"""``intraday_bars.feed``: where a bar came from (A6.1; ``replayed`` since A6.5)."""

ErrorKind = Literal["auth", "rate", "network", "provider", "not_supported"]

MINUTE = timedelta(minutes=1)


# --- Data ---------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FeedBar:
    """One normalised one-minute bar. ``ts`` is the bar's **open**, aware UTC."""

    symbol: str
    ts: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    feed: FeedTag
    source: str
    """``intraday_bars.source``: the provider and feed, e.g. ``alpaca_iex``."""

    def __post_init__(self) -> None:
        if self.ts.tzinfo is None or self.ts.utcoffset() != timedelta(0):
            raise ValueError("FeedBar.ts must be an aware UTC instant")


@dataclass(frozen=True, slots=True)
class Tick:
    """One trade-like event from a stream. ``replayed`` is true for SimulatedFeed."""

    symbol: str
    ts: datetime
    price: Decimal
    size: int
    feed: FeedTag
    replayed: bool = False

    @property
    def label(self) -> str:
        return "Replayed" if self.replayed else "Live"


@dataclass(frozen=True, slots=True)
class RateLimitSpec:
    """A documented limit: ``calls`` per ``per_seconds``."""

    calls: int
    per_seconds: float


@dataclass(frozen=True, slots=True)
class Capabilities:
    history: bool
    """``minute_bars`` is built."""
    stream: bool
    """``stream`` is built (A6.5/A6.6 for the real feeds; SimulatedFeed now)."""
    coverage: tuple[FeedTag, ...]
    """The feed tags this provider's bars carry."""
    symbols_limit: int | None = None
    """Most symbols on one stream (None: not stated or no stream)."""
    history_days: int | None = None
    """How far back history goes on the free plan (None: not limited or not stated)."""
    rate_limits: tuple[RateLimitSpec, ...] = ()
    notes: str = ""


# --- Errors -------------------------------------------------------------------


class FeedError(RuntimeError):
    """A provider call failed. ``str()`` is a fixed message: no key, URL query or body."""

    kind: ErrorKind = "provider"

    def __init__(
        self,
        provider: str,
        message: str,
        *,
        status: int | None = None,
        retry_after: float | None = None,
    ) -> None:
        self.provider = provider
        self.status = status
        self.retry_after = retry_after
        super().__init__(f"{provider}: {message}" + (f" (HTTP {status})" if status else ""))

    @property
    def summary(self) -> str:
        """The fixed text kept in ``job_runs.error``."""
        return f"{self.provider} {self.kind} error"


class FeedAuthError(FeedError):
    kind: ErrorKind = "auth"


class FeedRateError(FeedError):
    kind: ErrorKind = "rate"


class FeedNetworkError(FeedError):
    kind: ErrorKind = "network"


class FeedProviderError(FeedError):
    """The provider answered, but not in the documented shape, or refused the query."""

    kind: ErrorKind = "provider"


class NotSupported(FeedError):
    """The capability is not built or not on the free plan; carries the reason."""

    kind: ErrorKind = "not_supported"


class FeedNotConfigured(RuntimeError):
    """The provider's key env var is blank: the provider is off on this server."""


def classify_status(provider: str, status: int, retry_after: float | None = None) -> FeedError:
    """Map an HTTP status to a classified error with a fixed message."""
    if status in (401, 403):
        return FeedAuthError(provider, "the key was refused or lacks access", status=status)
    if status == 429:
        return FeedRateError(provider, "rate limit reached", status=status, retry_after=retry_after)
    if status >= 500:
        return FeedNetworkError(provider, "provider unavailable", status=status)
    return FeedProviderError(provider, "request refused", status=status)


# --- Symbols ------------------------------------------------------------------


def us_symbol(ticker: str) -> str:
    """A StockViz US ticker, upper-cased; refuses Indian and index tickers.

    US feeds never get an NSE/BSE symbol (``RELIANCE.NS``, ``^NSEI``) or an
    index (``^GSPC``): only plain US listings, which trade on XNYS hours.
    """
    value = ticker.strip().upper()
    if not value or value.startswith("^") or venue_for_ticker(value) != NEW_YORK_VENUE:
        raise ValueError(f"{ticker!r} is not a US stock or ETF ticker")
    if not all(ch.isalnum() or ch in ".-" for ch in value):
        raise ValueError(f"{ticker!r} is not a US stock or ETF ticker")
    return value


# --- Stream reconnect ---------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Backoff:
    """Exponential reconnect delays: base, base x factor, ... capped at ``cap``."""

    base: float = 1.0
    factor: float = 2.0
    cap: float = 60.0
    max_attempts: int = 8

    def delay(self, attempt: int) -> float:
        return min(self.cap, self.base * self.factor**attempt)


DEFAULT_BACKOFF = Backoff()

AsyncSleep = Callable[[float], Awaitable[None]]


async def reconnecting[T](
    connect: Callable[[], AsyncIterator[T]],
    *,
    backoff: Backoff = DEFAULT_BACKOFF,
    sleep: AsyncSleep = asyncio.sleep,
    on_reconnect: Callable[[int, FeedError], None] | None = None,
) -> AsyncIterator[T]:
    """Yield from ``connect()``, reconnecting after a network or rate error.

    An auth or provider error ends the stream at once (a wrong key does not
    get better by retrying). A rate error waits at least its ``retry_after``.
    The attempt counter resets once a connection yields an item. After
    ``max_attempts`` failed connections in a row the last error is raised.
    """
    attempt = 0
    while True:
        try:
            async for item in connect():
                attempt = 0
                yield item
            return
        except (FeedNetworkError, FeedRateError) as exc:
            if attempt >= backoff.max_attempts:
                raise
            wait = backoff.delay(attempt)
            if exc.retry_after is not None:
                wait = max(wait, exc.retry_after)
            if on_reconnect is not None:
                on_reconnect(attempt + 1, exc)
            attempt += 1
            await sleep(wait)


# --- Protocols ----------------------------------------------------------------


@runtime_checkable
class FeedProvider(Protocol):
    name: str
    label: str
    capabilities: Capabilities

    @property
    def configured(self) -> bool: ...

    def minute_bars(self, symbol: str, start: datetime, end: datetime) -> list[FeedBar]:
        """One-minute bars opening in [start, end), oldest first, aware UTC."""
        ...

    def stream(self, symbols: Sequence[str]) -> AsyncIterator[Tick | FeedBar]: ...


@dataclass(frozen=True, slots=True)
class BrokerAnswer:
    supported: bool
    reason: str = ""
    value: object = None


@runtime_checkable
class BrokerProvider(Protocol):
    name: str
    label: str

    def status(self) -> BrokerAnswer: ...
    def login_url(self) -> BrokerAnswer: ...
    def import_fills(self, data: bytes) -> BrokerAnswer: ...
    def export_basket(self, orders: Sequence[dict[str, object]]) -> BrokerAnswer: ...


@dataclass
class StubBroker:
    """A broker whose hooks are not built yet: every method says why (A6.11)."""

    name: str
    label: str
    reason: str = "not built yet (A6.11: broker CSV maps and the basket export)"
    _answer: BrokerAnswer = field(init=False)

    def __post_init__(self) -> None:
        self._answer = BrokerAnswer(supported=False, reason=self.reason)

    def status(self) -> BrokerAnswer:
        return self._answer

    def login_url(self) -> BrokerAnswer:
        return self._answer

    def import_fills(self, data: bytes) -> BrokerAnswer:
        return self._answer

    def export_basket(self, orders: Sequence[dict[str, object]]) -> BrokerAnswer:
        return self._answer


def utc(value: datetime) -> datetime:
    """Aware UTC; a naive value is taken as UTC (the ledger's convention)."""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
