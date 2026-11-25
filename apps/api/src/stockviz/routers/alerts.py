"""`/v1/alerts` — per-user alert rules and their history (Phase 7.1).

A rule has a kind (``price``, ``technical``; ``news`` and ``portfolio`` from
7.2) and is judged once per completed session by ``services/alerts`` in the
nightly cron. It fires when its condition newly becomes true (audit RS-8),
and every firing is kept in ``alert_events``. ``POST /{id}/dismiss`` marks the
last firing read; ``POST /{id}/rearm`` restarts a rule that fired once;
``PATCH /{id}`` pauses or resumes it.

A2.3: ``kind: "rule"`` judges a Rule DSL setup version (``setup_version_id``:
your own setup's or a preset's; another user's is 404, an archived setup's
409, a rule that no longer compiles 422) on one ticker. The setup's name,
version and canonical text are copied into ``params`` so the rule can be
worded without a lookup. ``PATCH`` with a new ``setup_version_id`` points
it at another version and re-arms it.

All endpoints depend on ``UserIdDep`` so the caller must present a valid
signed JWT.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlmodel import Session, col, or_, select

from stockviz._time import utcnow
from stockviz.auth import UserIdDep
from stockviz.db import get_session
from stockviz.models import (
    Alert,
    AlertDirection,
    AlertEvent,
    AlertKind,
    AlertRepeat,
    Setup,
    Symbol,
)
from stockviz.schemas import AlertEventOut, AlertIn, AlertOut, AlertPatch
from stockviz.services.alerts import RuleError, describe, validate_rule
from stockviz.services.setups import store as setups
from stockviz.services.setups.rules import compile_or_422

router = APIRouter(prefix="/v1/alerts", tags=["alerts"])

SessionDep = Annotated[Session, Depends(get_session)]

MAX_ACTIVE_ALERTS_PER_USER = 100
"""Cap on active rules one user may hold.

The alerts table had no per-user bound, so a script could add rows until the
evaluation pass — which walks every active rule — became the slowest thing the
nightly run does. Rules that fired once are history and don't count.
"""

SUPPORTED_KINDS = frozenset(AlertKind)


def _alert_out(alert: Alert, currency: str | None) -> AlertOut:
    """A rule with its symbol's currency and its sentence."""
    return AlertOut.model_validate(alert).model_copy(
        update={"currency": currency or "USD", "description": describe(alert)}
    )


def _currency_of(session: Session, ticker: str | None) -> str | None:
    symbol = session.get(Symbol, ticker) if ticker else None
    return symbol.currency if symbol else None


def _rule_params(session: Session, version_id: int, user_id: int) -> dict:
    """What a rule alert keeps about its setup version (checked to be visible)."""
    try:
        version = setups.visible_version(session, version_id, user_id)
    except setups.SetupNotFound as exc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"Setup version {version_id} not found"
        ) from exc
    setup = session.get(Setup, version.setup_id)
    assert setup is not None
    if setup.archived_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "That setup is archived")
    rule = compile_or_422(version.rule_text)
    return {
        "setup_id": setup.id,
        "setup_name": setup.name,
        "version": version.version,
        "canonical": rule.canonical_text,
        "hash": rule.hash,
        "preset": setup.is_preset,
    }


def _owned(session: Session, alert_id: int, user_id: int) -> Alert:
    alert = session.get(Alert, alert_id)
    if alert is None or alert.user_id != user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Alert not found")
    return alert


@router.get("", response_model=list[AlertOut])
def list_alerts(session: SessionDep, user_id: UserIdDep) -> list[AlertOut]:
    """Return every rule the user owns, newest first."""

    stmt = (
        select(Alert, Symbol.currency)
        .join(Symbol, Symbol.ticker == Alert.ticker, isouter=True)  # type: ignore[arg-type]
        .where(Alert.user_id == user_id)
        .order_by(Alert.created_at.desc())  # type: ignore[attr-defined]
    )
    return [_alert_out(alert, currency) for alert, currency in session.exec(stmt).all()]


@router.get("/events", response_model=list[AlertEventOut])
def list_events(
    session: SessionDep,
    user_id: UserIdDep,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[AlertEvent]:
    """Every firing of the user's rules, newest first (the alert history)."""
    return list(
        session.exec(
            select(AlertEvent)
            .where(AlertEvent.user_id == user_id)
            .order_by(col(AlertEvent.created_at).desc(), col(AlertEvent.id).desc())
            .limit(limit)
        ).all()
    )


@router.get("/{alert_id}/events", response_model=list[AlertEventOut])
def list_rule_events(alert_id: int, session: SessionDep, user_id: UserIdDep) -> list[AlertEvent]:
    """One rule's firings, newest first."""
    _owned(session, alert_id, user_id)
    return list(
        session.exec(
            select(AlertEvent)
            .where(AlertEvent.alert_id == alert_id)
            .order_by(col(AlertEvent.created_at).desc(), col(AlertEvent.id).desc())
            .limit(500)
        ).all()
    )


@router.post("", response_model=AlertOut, status_code=status.HTTP_201_CREATED)
def create_alert(body: AlertIn, session: SessionDep, user_id: UserIdDep) -> AlertOut:
    kind = AlertKind(body.kind)
    if kind not in SUPPORTED_KINDS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{kind.value} alerts are not available")
    ticker = body.ticker.upper() if body.ticker else None
    symbol = session.get(Symbol, ticker) if ticker else None
    if ticker and symbol is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Symbol {ticker!r} not found")
    try:
        params = validate_rule(
            kind,
            ticker=ticker,
            direction=body.direction,
            target_price=body.target_price,
            params=body.params,
        )
    except RuleError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    if kind == AlertKind.RULE:
        if body.setup_version_id is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "a rule alert needs setup_version_id")
        params = _rule_params(session, body.setup_version_id, user_id)
    elif body.setup_version_id is not None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "setup_version_id is for rule alerts only")

    active = (
        session.exec(
            select(func.count())  # type: ignore[call-overload]
            .select_from(Alert)
            .where(
                Alert.user_id == user_id,
                col(Alert.paused).is_(False),
                or_(
                    col(Alert.repeat) == AlertRepeat.EVERY_CROSS, col(Alert.triggered_at).is_(None)
                ),
            )
        ).one()
        or 0
    )
    if active >= MAX_ACTIVE_ALERTS_PER_USER:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"You already have {MAX_ACTIVE_ALERTS_PER_USER} active alerts. "
            "Delete or pause some before adding more.",
        )

    level = kind == AlertKind.PRICE and params is None
    now = utcnow()
    alert = Alert(
        user_id=user_id,
        ticker=ticker,
        kind=kind,
        direction=AlertDirection(body.direction) if level and body.direction else None,
        target_price=body.target_price if level else None,
        params=params,
        setup_version_id=body.setup_version_id if kind == AlertKind.RULE else None,
        repeat=AlertRepeat(body.repeat),
        cooldown_sessions=body.cooldown_sessions,
        created_at=now,
        armed_at=now,
    )
    session.add(alert)
    session.commit()
    session.refresh(alert)
    return _alert_out(alert, symbol.currency if symbol else None)


@router.patch("/{alert_id}", response_model=AlertOut)
def patch_alert(
    alert_id: int, body: AlertPatch, session: SessionDep, user_id: UserIdDep
) -> AlertOut:
    """Pause or resume a rule (resuming re-arms it from the current state), or
    point a rule alert at another setup version (which re-arms it)."""
    alert = _owned(session, alert_id, user_id)
    if body.setup_version_id is not None:
        if alert.kind != AlertKind.RULE:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "setup_version_id is for rule alerts only"
            )
        if body.setup_version_id != alert.setup_version_id:
            alert.params = _rule_params(session, body.setup_version_id, user_id)
            alert.setup_version_id = body.setup_version_id
            _rearm(alert)
    if body.paused is not None:
        if alert.paused and not body.paused:
            _rearm(alert)
        alert.paused = body.paused
    session.add(alert)
    session.commit()
    session.refresh(alert)
    return _alert_out(alert, _currency_of(session, alert.ticker))


def _rearm(alert: Alert) -> None:
    """Watch again from now: the starting state is the newest close known now."""
    alert.armed_at = utcnow()
    alert.last_state = None
    alert.last_bar_date = None
    alert.triggered_at = None
    alert.dismissed_at = None


@router.post("/{alert_id}/rearm", response_model=AlertOut)
def rearm_alert(alert_id: int, session: SessionDep, user_id: UserIdDep) -> AlertOut:
    """Restart a rule that fired (audit RS-8: alerts could not be re-armed)."""
    alert = _owned(session, alert_id, user_id)
    _rearm(alert)
    session.add(alert)
    session.commit()
    session.refresh(alert)
    return _alert_out(alert, _currency_of(session, alert.ticker))


@router.delete("/{alert_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_alert(alert_id: int, session: SessionDep, user_id: UserIdDep) -> None:
    alert = _owned(session, alert_id, user_id)
    session.delete(alert)
    session.commit()


@router.post("/{alert_id}/dismiss", response_model=AlertOut)
def dismiss_alert(alert_id: int, session: SessionDep, user_id: UserIdDep) -> AlertOut:
    """Mark a rule's last firing as read.

    Only a rule that fired can be dismissed — dismissing one that has not is
    a no-op that returns 422 so the UI can surface the mistake.
    """

    alert = _owned(session, alert_id, user_id)
    if alert.triggered_at is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Alert has not triggered yet")
    alert.dismissed_at = utcnow()
    session.add(alert)
    session.commit()
    session.refresh(alert)
    return _alert_out(alert, _currency_of(session, alert.ticker))
