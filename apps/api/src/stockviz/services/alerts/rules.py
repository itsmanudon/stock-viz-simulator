"""Alert rule validation and wording (Phase 7.1).

``validate_rule`` checks what a user asks for and returns the normalised
``params`` stored on the rule; ``describe`` turns a rule into a sentence the
UI and notifications show.

Kinds and their ``params``:

- ``price`` level: ``direction`` (above/below) and ``target_price`` columns,
  ``params`` empty. ``price`` move: ``{"move_pct": 5}`` — the close moved at
  least 5% from the previous close, either way.
- ``technical``: ``{"indicator": "rsi_14", "op": "below", "value": 30}`` or
  ``{"indicator": "close", "op": "above", "compare_to": "sma_200"}``. An
  operand is ``close`` or a registry token, with ``.output`` when the
  indicator has several (``macd.signal``, ``bb_20_2.upper``).
- ``news``: ``{"sentiment": "negative" | "positive" | "mixed" | null,
  "event_type": str | null}``.
- ``portfolio``: ``{"metric": "drawdown_pct" | "position_weight_pct" |
  "day_change_pct", "threshold": 10}``.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from stockviz.models import Alert, AlertDirection, AlertKind
from stockviz.services.indicators.engine import parse

TECHNICAL_OPS = ("above", "below")
NEWS_SENTIMENTS = ("negative", "positive", "mixed")
PORTFOLIO_METRICS = {
    "drawdown_pct": "the account's drawdown from its peak NAV",
    "position_weight_pct": "a holding's share of NAV",
    "day_change_pct": "the account's move in a session",
}


class RuleError(ValueError):
    """The rule as asked cannot be evaluated."""


def check_operand(token: str) -> str:
    """``close``, or a registry token with an optional ``.output``."""
    text = token.strip().lower()
    if text == "close":
        return text
    name, _, output = text.partition(".")
    try:
        request = parse(name)
    except ValueError as exc:
        raise RuleError(str(exc)) from exc
    outputs = request.spec.outputs
    if output:
        if output not in outputs:
            raise RuleError(f"{name} has outputs {', '.join(outputs)}, not {output!r}")
    elif len(outputs) > 1:
        raise RuleError(f"{name} has several outputs; name one: {', '.join(outputs)}")
    return text


def _number(raw: Any, field: str, *, positive: bool = False) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise RuleError(f"{field} must be a number") from exc
    if value != value or value in (float("inf"), float("-inf")):
        raise RuleError(f"{field} must be finite")
    if positive and value <= 0:
        raise RuleError(f"{field} must be positive")
    return value


def validate_rule(
    kind: AlertKind,
    *,
    ticker: str | None,
    direction: str | None,
    target_price: Decimal | None,
    params: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Return the ``params`` to store, or raise :class:`RuleError`."""
    params = dict(params or {})
    if kind != AlertKind.PORTFOLIO and not ticker:
        raise RuleError("ticker is required")
    if kind == AlertKind.PRICE:
        if "move_pct" in params:
            pct = _number(params["move_pct"], "move_pct", positive=True)
            if pct > 100:
                raise RuleError("move_pct must be at most 100")
            return {"move_pct": pct}
        if direction not in ("above", "below") or target_price is None:
            raise RuleError("a price alert needs direction (above/below) and target_price")
        if target_price <= 0:
            raise RuleError("target_price must be positive")
        return None
    if kind == AlertKind.TECHNICAL:
        indicator = check_operand(str(params.get("indicator", "")))
        op = params.get("op")
        if op not in TECHNICAL_OPS:
            raise RuleError("op must be 'above' or 'below'")
        has_value = params.get("value") is not None
        has_other = bool(params.get("compare_to"))
        if has_value == has_other:
            raise RuleError("give exactly one of value or compare_to")
        out: dict[str, Any] = {"indicator": indicator, "op": op}
        if has_value:
            out["value"] = _number(params["value"], "value")
        else:
            out["compare_to"] = check_operand(str(params["compare_to"]))
            if out["compare_to"] == indicator:
                raise RuleError("compare_to must differ from indicator")
        return out
    if kind == AlertKind.NEWS:
        sentiment = params.get("sentiment") or None
        if sentiment is not None and sentiment not in NEWS_SENTIMENTS:
            raise RuleError(f"sentiment must be one of {', '.join(NEWS_SENTIMENTS)}")
        event_type = (params.get("event_type") or None) and str(params["event_type"])[:128]
        return {"sentiment": sentiment, "event_type": event_type}
    if kind == AlertKind.PORTFOLIO:
        metric = params.get("metric")
        if metric not in PORTFOLIO_METRICS:
            raise RuleError(f"metric must be one of {', '.join(PORTFOLIO_METRICS)}")
        threshold = _number(params.get("threshold"), "threshold", positive=True)
        if threshold > 100:
            raise RuleError("threshold is a percentage, at most 100")
        return {"metric": metric, "threshold": threshold}
    raise RuleError(f"unknown kind {kind!r}")


def _operand_label(token: str) -> str:
    if token == "close":
        return "the close"
    name, _, output = token.partition(".")
    label = parse(name).spec.label
    args = "_".join(name.split("_")[1:]).replace("_", ", ")
    text = f"{label} {args}".strip()
    return f"{text} ({output})" if output else text


def describe(alert: Alert) -> str:
    """The rule in words, for lists and notifications."""
    p = alert.params or {}
    kind = AlertKind(alert.kind)
    if kind == AlertKind.PRICE:
        if "move_pct" in p:
            return f"{alert.ticker} moves {p['move_pct']:g}% or more in a session"
        direction = AlertDirection(alert.direction) if alert.direction else AlertDirection.ABOVE
        return f"{alert.ticker} closes {direction.value} {alert.target_price:,.2f}"
    if kind == AlertKind.TECHNICAL:
        rhs = f"{p['value']:g}" if "value" in p else _operand_label(p["compare_to"])
        return f"{alert.ticker}: {_operand_label(p['indicator'])} crosses {p['op']} {rhs}"
    if kind == AlertKind.NEWS:
        parts = [f"New {alert.ticker} news"]
        if p.get("sentiment"):
            parts.append(f"with {p['sentiment']} sentiment")
        if p.get("event_type"):
            parts.append(f"about {p['event_type']}")
        return " ".join(parts)
    what = PORTFOLIO_METRICS.get(p.get("metric", ""), "a portfolio figure")
    return f"Alert when {what} reaches {p.get('threshold', 0):g}%"
