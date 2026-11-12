"""Alert rules, evaluation and history (Phase 7).

See ``engine.py`` for how rules are judged and ``rules.py`` for what each
kind accepts.
"""

from __future__ import annotations

from sqlmodel import Session

from stockviz.models import Alert, AlertEvent


def on_alert_fired(session: Session, alert: Alert, event: AlertEvent) -> None:
    """Hook run in the firing's transaction (notifications attach here, 7.2)."""


from stockviz.services.alerts.engine import evaluate_pending_alerts  # noqa: E402
from stockviz.services.alerts.rules import RuleError, describe, validate_rule  # noqa: E402

__all__ = ["RuleError", "describe", "evaluate_pending_alerts", "on_alert_fired", "validate_rule"]
