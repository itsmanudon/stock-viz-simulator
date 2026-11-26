"""Thesis kill switches (A7.5, M5.6): a thesis's kill rule is judged nightly.

A thesis with a kill rule owns one **rule alert** (A2.3's engine: armed from
the newest bar known at arming, fires once on the false-to-true crossing,
de-duplicated per bar, notifies and stages delivery). The alert is linked by
``alerts.params["thesis_id"]``; its setup version is a version of the user's
"Thesis kill switches" setup (one version per distinct rule, the same rule is
the same version). So nothing new is evaluated or stored: the kill switch is
an alert the thesis keeps in step.

- Setting or changing the kill rule points the alert at the rule's version
  and re-arms it; removing the rule deletes the alert.
- Closing or invalidating the thesis pauses the alert.
- A firing does not change the thesis: the user decides (the memo says so).
"""

from __future__ import annotations

from typing import Any

from sqlmodel import Session, col, select

from stockviz._time import utcnow
from stockviz.models import Alert, AlertEvent, Thesis
from stockviz.models.alert import AlertKind, AlertRepeat
from stockviz.services.backtest.strategy_run import inline_rule_version
from stockviz.services.dsl import compile_rule
from stockviz.services.theses import tickers_for

KILL_SETUP_NAME = "Thesis kill switches"
KILL_SETUP_KIND = "alert"


def kill_alert(session: Session, thesis: Thesis) -> Alert | None:
    """The alert linked to ``thesis``, if any."""
    rows = session.exec(
        select(Alert).where(col(Alert.user_id) == thesis.user_id, col(Alert.kind) == AlertKind.RULE)
    ).all()
    return next((a for a in rows if (a.params or {}).get("thesis_id") == thesis.id), None)


def sync_kill_alert(session: Session, thesis: Thesis) -> Alert | None:
    """Keep the thesis's alert in step with its kill rule and status. Does not commit."""
    assert thesis.id is not None
    alert = kill_alert(session, thesis)
    if not thesis.kill_rule_text:
        if alert is not None:
            session.delete(alert)
        return None
    ticker = tickers_for(session, [thesis.instrument_id]).get(thesis.instrument_id)
    if ticker is None:
        return alert
    compiled = compile_rule(thesis.kill_rule_text)
    version = inline_rule_version(
        session, thesis.user_id, compiled, name=KILL_SETUP_NAME, kind=KILL_SETUP_KIND,
        description="Kill rules of your theses (A7.5); one version per distinct rule.",
    )  # fmt: skip
    params: dict[str, Any] = {
        "setup_id": version.setup_id,
        "setup_name": KILL_SETUP_NAME,
        "version": version.version,
        "canonical": compiled.canonical_text,
        "hash": compiled.hash,
        "preset": False,
        "thesis_id": thesis.id,
        "thesis_title": thesis.title,
    }
    now = utcnow()
    if alert is None:
        alert = Alert(user_id=thesis.user_id, ticker=ticker, kind=AlertKind.RULE,
                      setup_version_id=version.id, params=params, repeat=AlertRepeat.ONCE,
                      created_at=now, armed_at=now)  # fmt: skip
    elif alert.setup_version_id != version.id:
        alert.setup_version_id = version.id
        alert.params = params
        alert.armed_at, alert.last_state, alert.last_bar_date = now, None, None
        alert.triggered_at = None
    else:
        alert.params = params  # the title may have changed
    alert.paused = thesis.status != "open"
    session.add(alert)
    return alert


def kill_state(session: Session, thesis: Thesis) -> dict[str, Any]:
    """What the thesis shows about its kill switch: armed, paused, fired (when)."""
    alert = kill_alert(session, thesis)
    if alert is None:
        return {"kill_alert_id": None, "kill_state": "none", "kill_fired_at": None}
    fired = session.exec(
        select(AlertEvent)
        .where(col(AlertEvent.alert_id) == alert.id)
        .order_by(col(AlertEvent.id).desc())
    ).first()
    state = "fired" if fired is not None else ("paused" if alert.paused else "armed")
    return {
        "kill_alert_id": alert.id,
        "kill_state": state,
        "kill_fired_at": fired.created_at if fired is not None else None,
        "kill_fired_on": fired.bar_date if fired is not None else None,
    }
