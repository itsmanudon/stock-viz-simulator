"""Alert rules, evaluation and history (Phase 7).

See ``engine.py`` for how rules are judged and ``rules.py`` for what each
kind accepts.
"""

from __future__ import annotations

from sqlmodel import Session

from stockviz.models import Alert, AlertEvent


def on_alert_fired(session: Session, alert: Alert, event: AlertEvent) -> None:
    """Every firing becomes a notification, in the firing's transaction (7.2)."""
    from stockviz.models import NotificationCategory
    from stockviz.services.alerts.rules import describe
    from stockviz.services.notifications import notify

    notify(
        session,
        user_id=alert.user_id,
        category=NotificationCategory.ALERT,
        title=describe(alert),
        body=event.message,
        link=f"/alerts?rule={alert.id}",
        source_key=f"alert_event:{event.dedupe_key}",
    )


from stockviz.services.alerts.engine import evaluate_pending_alerts  # noqa: E402
from stockviz.services.alerts.rules import RuleError, describe, validate_rule  # noqa: E402

__all__ = ["RuleError", "describe", "evaluate_pending_alerts", "on_alert_fired", "validate_rule"]
