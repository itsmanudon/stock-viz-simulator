"""`/v1/broker/status` — what the app can do with each broker (A5.7, M1.7).

Signed in. StockViz has no live broker connection: this reports whether a
broker's app is configured on this server (never the key), the caller's
imported books for that broker, and a state the web turns into plain words.
No login, callback or token table (deferred to A6). A6.3 adds `/v1/broker/feeds`:
the US market-data feeds (`services/feeds/status.py`). See
``services/brokers``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import Session

from stockviz._time import utcnow
from stockviz.auth import UserIdDep
from stockviz.db import get_session
from stockviz.services.brokers import OFFLINE_WINDOW, broker_statuses
from stockviz.settings import Settings, get_settings

router = APIRouter(prefix="/v1/broker", tags=["brokers"])

SessionDep = Annotated[Session, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


class BrokerStatusItemOut(BaseModel):
    broker: Literal["zerodha"]
    label: str
    provider: Literal["kite"]
    configured: bool
    """The broker's app is set up on this server. The key is never returned."""
    state: Literal["not_configured", "not_connected", "offline", "snapshot_only"]
    live_data: bool
    """Always false: no live broker data is built (A6 needs a paid app)."""
    imported_books: int
    """The caller's active imported books for this broker."""
    last_imported_at: datetime | None
    """The newest tradebook import into those books (A5.3; null until then)."""
    last_snapshot_at: datetime | None
    last_failure_at: datetime | None


class BrokerStatusOut(BaseModel):
    brokers: list[BrokerStatusItemOut]
    offline_window_hours: int
    checked_at: datetime


@router.get("/status", response_model=BrokerStatusOut)
def broker_status(
    session: SessionDep, settings: SettingsDep, user_id: UserIdDep
) -> BrokerStatusOut:
    now = utcnow()
    return BrokerStatusOut(
        brokers=[
            BrokerStatusItemOut(
                broker="zerodha",
                label=s.label,
                provider="kite",
                configured=s.configured,
                state=s.state,
                live_data=False,
                imported_books=s.imported_books,
                last_imported_at=s.last_imported_at,
                last_snapshot_at=s.last_snapshot_at,
                last_failure_at=s.last_failure_at,
            )
            for s in broker_statuses(session, settings, user_id, now=now)
        ],
        offline_window_hours=int(OFFLINE_WINDOW.total_seconds() // 3600),
        checked_at=now,
    )


class FeedCapabilitiesOut(BaseModel):
    history: bool
    stream: bool
    coverage: list[Literal["iex", "sip", "kite", "file", "replayed"]]
    symbols_limit: int | None
    history_days: int | None
    rate_limits: list[str]
    notes: str


class FeedStatusItemOut(BaseModel):
    provider: Literal["alpaca", "tiingo", "massive", "finnhub"]
    label: str
    configured: bool
    """The provider's key is set on this server. The key is never returned."""
    state: Literal["not_configured", "configured", "ok", "error"]
    key_env_vars: list[str]
    """Names of the env vars that turn it on (names only)."""
    capabilities: FeedCapabilitiesOut
    last_success_at: datetime | None
    last_failure_at: datetime | None
    last_error: str | None
    """A fixed summary of the newest failed backfill while ``error``."""


class StreamStatusOut(BaseModel):
    """A6.5: a stream the worker has run (``feed_streams``)."""

    name: str
    label: str
    live: bool
    """False for the ``simulated`` replay: never called live."""
    state: Literal["streaming", "closed", "error"]
    stale: bool
    """It said ``streaming`` but has not reported for 5 minutes."""
    symbols: list[str]
    started_at: datetime
    stopped_at: datetime | None
    last_tick_at: datetime | None
    last_bar_at: datetime | None
    bars_written: int
    alerts_fired: int
    error: str | None


class FeedStatusOut(BaseModel):
    feeds: list[FeedStatusItemOut]
    streams: list[StreamStatusOut]
    offline_window_hours: int
    checked_at: datetime


@router.get("/feeds", response_model=FeedStatusOut)
def feed_status(session: SessionDep, settings: SettingsDep, user_id: UserIdDep) -> FeedStatusOut:
    """A6.3: the US market-data feeds; A6.5: the streams the worker has run."""
    from stockviz.services.feeds.status import feed_statuses, stream_statuses

    now = utcnow()
    return FeedStatusOut(
        feeds=[
            FeedStatusItemOut(
                provider=s.provider,  # pyright: ignore[reportArgumentType]
                label=s.label,
                configured=s.configured,
                state=s.state,
                key_env_vars=list(s.key_env_vars),
                capabilities=FeedCapabilitiesOut(
                    history=s.capabilities.history,
                    stream=s.capabilities.stream,
                    coverage=list(s.capabilities.coverage),
                    symbols_limit=s.capabilities.symbols_limit,
                    history_days=s.capabilities.history_days,
                    rate_limits=[
                        f"{r.calls} per {int(r.per_seconds)} s" for r in s.capabilities.rate_limits
                    ],
                    notes=s.capabilities.notes,
                ),
                last_success_at=s.last_success_at,
                last_failure_at=s.last_failure_at,
                last_error=s.last_error,
            )
            for s in feed_statuses(session, settings, now=now)
        ],
        streams=[
            StreamStatusOut(
                name=r.name,
                label=r.label,
                live=r.live,
                state=r.state,  # pyright: ignore[reportArgumentType]
                stale=r.stale,
                symbols=list(r.symbols),
                started_at=r.started_at,
                stopped_at=r.stopped_at,
                last_tick_at=r.last_tick_at,
                last_bar_at=r.last_bar_at,
                bars_written=r.bars_written,
                alerts_fired=r.alerts_fired,
                error=r.error,
            )
            for r in stream_statuses(session, now=now)
        ],
        offline_window_hours=int(OFFLINE_WINDOW.total_seconds() // 3600),
        checked_at=now,
    )


KITE_BASKET_URL = "https://kite.zerodha.com/connect/basket"
"""Kite's offsite basket (Kite Connect v3 "Offsite order execution", read
26 Nov 2026). The browser POSTs a form there; this server never does."""


class BasketHandoffOut(BaseModel):
    """A6.11 (M10.5): how a basket can leave StockViz. StockViz never places an
    order: a basket downloads as CSV or JSON, and with ``KITE_API_KEY`` set the
    web also offers Kite's basket form, which the user's browser posts and the
    user confirms inside Zerodha."""

    kite_basket: bool
    """``KITE_API_KEY`` is set on this server."""
    kite_api_key: str | None
    """The Kite app's public ``api_key`` while ``kite_basket``, else null. Kite's
    documented basket form carries it as a field in the user's browser, so it
    is not a secret; ``KITE_API_SECRET`` is never returned."""
    kite_basket_url: str | None
    exports: list[Literal["csv", "json"]]


@router.get("/basket", response_model=BasketHandoffOut)
def basket_handoff(settings: SettingsDep, user_id: UserIdDep) -> BasketHandoffOut:
    key = settings.kite_api_key.strip()
    return BasketHandoffOut(
        kite_basket=bool(key),
        kite_api_key=key or None,
        kite_basket_url=KITE_BASKET_URL if key else None,
        exports=["csv", "json"],
    )
