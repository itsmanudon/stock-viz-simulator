"""`/v1/alerts` — per-user price alerts.

A user creates an alert with a ticker, direction (``above``/``below``), and a
target price. The scheduler flips ``triggered_at`` from null to the trigger
time when a fresh quote crosses the threshold (see ``services/alerts.py``).
Dismissing is a UI action: ``POST /v1/alerts/{id}/dismiss``.

All endpoints depend on ``UserIdDep`` so the caller must present a valid
signed JWT.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select

from stockviz._time import utcnow
from stockviz.auth import UserIdDep
from stockviz.db import get_session
from stockviz.models import Alert, AlertDirection, Symbol
from stockviz.schemas import AlertIn, AlertOut

router = APIRouter(prefix="/v1/alerts", tags=["alerts"])

SessionDep = Annotated[Session, Depends(get_session)]


@router.get("", response_model=list[AlertOut])
def list_alerts(session: SessionDep, user_id: UserIdDep) -> list[Alert]:
    """Return every alert the user owns, newest first."""

    stmt = (
        select(Alert).where(Alert.user_id == user_id).order_by(Alert.created_at.desc())  # type: ignore[attr-defined]
    )
    return list(session.exec(stmt).all())


@router.post("", response_model=AlertOut, status_code=status.HTTP_201_CREATED)
def create_alert(body: AlertIn, session: SessionDep, user_id: UserIdDep) -> Alert:
    if body.target_price <= 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "target_price must be positive")
    ticker = body.ticker.upper()
    if session.get(Symbol, ticker) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Symbol {ticker!r} not found")

    alert = Alert(
        user_id=user_id,
        ticker=ticker,
        direction=AlertDirection(body.direction),
        target_price=body.target_price,
    )
    session.add(alert)
    session.commit()
    session.refresh(alert)
    return alert


@router.delete("/{alert_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_alert(alert_id: int, session: SessionDep, user_id: UserIdDep) -> None:
    alert = session.get(Alert, alert_id)
    if alert is None or alert.user_id != user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Alert not found")
    session.delete(alert)
    session.commit()


@router.post("/{alert_id}/dismiss", response_model=AlertOut)
def dismiss_alert(alert_id: int, session: SessionDep, user_id: UserIdDep) -> Alert:
    """Mark a triggered alert as read.

    Only triggered alerts can be dismissed — dismissing an un-triggered alert
    is a no-op that returns 422 so the UI can surface the mistake.
    """

    alert = session.get(Alert, alert_id)
    if alert is None or alert.user_id != user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Alert not found")
    if alert.triggered_at is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Alert has not triggered yet")
    alert.dismissed_at = utcnow()
    session.add(alert)
    session.commit()
    session.refresh(alert)
    return alert
