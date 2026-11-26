"""`/v1/broker/status` — what the app can do with each broker (A5.7, M1.7).

Signed in. StockViz has no live broker connection: this reports whether a
broker's app is configured on this server (never the key), the caller's
imported books for that broker, and a state the web turns into plain words.
No login, callback or token table (deferred to A6). See
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
