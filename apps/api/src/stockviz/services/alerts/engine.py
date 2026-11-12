"""Alert evaluation (Phase 7.1): one pass per completed session.

Each active rule is judged on its ticker's newest daily bar:

- **Crossing, not state (audit RS-8).** A rule fires when its condition is
  true on the new bar and was false at the last judged bar. A rule never
  judged before takes its starting state from the newest bar that was known
  when it was armed (``armed_at``; the LG-5 rule orders use), so an alert set
  while RSI is already 25 waits for the next cross below 30.
- **Event rules** (a session move of N%) fire on every bar where they hold,
  never on a bar that was already known when the rule was armed.
- **Once per bar.** A bar already judged is skipped, so the nightly cron and
  the hourly worker can both run without double counting; and each firing's
  ``dedupe_key`` (``<rule>:<bar date>``) is unique in ``alert_events``.
- ``once`` rules stop after firing; ``every_cross`` rules fire again on a
  later cross once ``cooldown_sessions`` bars have passed.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from itertools import pairwise

import pandas as pd
from sqlmodel import Session, col, or_, select

from stockviz._time import utcnow
from stockviz.models import Alert, AlertDirection, AlertEvent, AlertKind, AlertRepeat, PriceBar
from stockviz.services.indicators.engine import compute, frame, parse
from stockviz.services.instruments import instrument_of
from stockviz.services.markets.calendar import latest_completed_session, venue_for_ticker

logger = logging.getLogger(__name__)

PRICE_BARS = 60
"""Bars read for a price rule: enough for the cooldown count and arming."""

TECHNICAL_EXTRA_BARS = 300
"""Bars read beyond an indicator's lookback, so its value has settled."""


@dataclass(frozen=True)
class Point:
    """A rule's condition on one bar."""

    bar_date: date
    state: bool | None  # None while the indicator is still warming up
    observed: Decimal | None
    threshold: Decimal | None


def known_at_arming(alert: Alert) -> date:
    """The newest session whose close the user could see when the rule was armed."""
    armed = alert.armed_at or alert.created_at
    venue = venue_for_ticker(alert.ticker) if alert.ticker else "XNYS"
    return latest_completed_session(armed.replace(tzinfo=UTC), venue)


def _bars(session: Session, ticker: str, limit: int) -> list[PriceBar]:
    rows = session.exec(
        select(PriceBar)
        .where(PriceBar.instrument_id == instrument_of(ticker), PriceBar.interval == "1d")
        .order_by(col(PriceBar.ts).desc())
        .limit(limit)
    ).all()
    return list(reversed(rows))


def _dec(value: float | Decimal | None) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if math.isnan(value) or math.isinf(value):
        return None
    return Decimal(str(round(value, 8)))


def _price_points(alert: Alert, bars: list[PriceBar]) -> list[Point]:
    params = alert.params or {}
    if "move_pct" in params:
        threshold = Decimal(str(params["move_pct"]))
        points = []
        for prev, bar in pairwise(bars):
            if prev.close <= 0:
                continue
            move = (bar.close / prev.close - 1) * 100
            points.append(Point(bar.ts.date(), abs(move) >= threshold, move, threshold))
        return points
    assert alert.target_price is not None
    above = alert.direction == AlertDirection.ABOVE
    return [
        Point(
            bar.ts.date(),
            bar.close >= alert.target_price if above else bar.close <= alert.target_price,
            bar.close,
            alert.target_price,
        )
        for bar in bars
    ]


def _series(token: str, f: pd.DataFrame) -> pd.Series:
    if token == "close":
        return pd.Series(f["close"], index=f.index, dtype=float)
    name, _, output = token.partition(".")
    outputs = compute(parse(name), f)
    series = outputs[output] if output else next(iter(outputs.values()))
    return pd.Series(series, index=f.index, dtype=float)


def _lookback(token: str) -> int:
    return 0 if token == "close" else parse(token.partition(".")[0]).lookback


def _technical_points(alert: Alert, bars: list[PriceBar]) -> list[Point]:
    params = alert.params or {}
    f = frame([(b.ts, b.open, b.high, b.low, b.close, b.volume) for b in bars])
    lhs = _series(params["indicator"], f)
    if "value" in params:
        rhs = pd.Series(float(params["value"]), index=f.index)
    else:
        rhs = _series(params["compare_to"], f)
    above = params["op"] == "above"
    points = []
    for ts, left, right in zip(f.index, lhs, rhs, strict=True):
        if pd.isna(left) or pd.isna(right):
            state = None
        else:
            state = bool(left > right) if above else bool(left < right)
        points.append(Point(ts.date(), state, _dec(float(left)), _dec(float(right))))
    return points


def _bars_needed(alert: Alert) -> int:
    if alert.kind == AlertKind.TECHNICAL:
        params = alert.params or {}
        tokens = [params.get("indicator", "close"), params.get("compare_to") or "close"]
        return max(_lookback(t) for t in tokens) + TECHNICAL_EXTRA_BARS
    return PRICE_BARS


def _message(alert: Alert, point: Point) -> str:
    from stockviz.services.alerts.rules import describe

    day = point.bar_date.isoformat()
    params = alert.params or {}
    if alert.kind == AlertKind.PRICE and "move_pct" in params:
        return (
            f"{alert.ticker} moved {point.observed:+.2f}% on {day}, "
            f"past your {params['move_pct']:g}% threshold."
        )
    if alert.kind == AlertKind.PRICE:
        return (
            f"{alert.ticker} closed at {point.observed:,.2f} on {day}: "
            f"{alert.direction.value if alert.direction else ''} your {alert.target_price:,.2f}."
        )
    observed = f"{point.observed:,.2f}" if point.observed is not None else "?"
    threshold = f"{point.threshold:,.2f}" if point.threshold is not None else "?"
    return f"{describe(alert)} on {day} ({observed} against {threshold})."


def _active_rules(session: Session, ticker: str | None) -> list[Alert]:
    stmt = select(Alert).where(
        col(Alert.paused).is_(False),
        col(Alert.kind).in_([AlertKind.PRICE, AlertKind.TECHNICAL]),
        or_(col(Alert.repeat) == AlertRepeat.EVERY_CROSS, col(Alert.triggered_at).is_(None)),
    )
    if ticker is not None:
        stmt = stmt.where(Alert.instrument_id == instrument_of(ticker))
    return list(session.exec(stmt.order_by(col(Alert.id))).all())


def _judge(
    alert: Alert, points: list[Point], known: Callable[[Alert], date]
) -> tuple[bool, Point | None]:
    """Whether ``alert`` fires on its newest bar; mutates its evaluation state."""
    if not points:
        return False, None
    current = points[-1]
    if alert.last_bar_date is not None and current.bar_date <= alert.last_bar_date:
        return False, None  # this bar was judged already
    if current.state is None:
        return False, None  # still warming up; judge a later bar
    event_rule = alert.kind == AlertKind.PRICE and "move_pct" in (alert.params or {})
    if alert.last_state is None:
        cutoff = known(alert)
        if current.bar_date <= cutoff:
            fire = False  # the user could already see this bar: arm only
        elif event_rule:
            fire = bool(current.state)
        else:
            prior = [p for p in points if p.bar_date <= cutoff]
            fire = bool(current.state) and not (prior and prior[-1].state)
    else:
        fire = bool(current.state) and (event_rule or not alert.last_state)
    if fire and alert.repeat == AlertRepeat.EVERY_CROSS and alert.last_fired_bar_date:
        since = sum(1 for p in points if p.bar_date > alert.last_fired_bar_date)
        if since < alert.cooldown_sessions:
            fire = False
    alert.last_state = current.state
    alert.last_bar_date = current.bar_date
    return fire, current


def fire(
    session: Session,
    alert: Alert,
    *,
    session_date: date,
    bar_date: date | None,
    observed: Decimal | None,
    threshold: Decimal | None,
    message: str,
    source: str,
    dedupe_key: str,
    now: datetime,
) -> AlertEvent | None:
    """Record one firing, unless ``dedupe_key`` was recorded already. No commit."""
    exists = session.exec(select(AlertEvent.id).where(AlertEvent.dedupe_key == dedupe_key)).first()
    if exists is not None:
        return None
    assert alert.id is not None
    event = AlertEvent(
        alert_id=alert.id,
        user_id=alert.user_id,
        kind=str(alert.kind),
        ticker=alert.ticker,
        session_date=session_date,
        bar_date=bar_date,
        observed=observed,
        threshold=threshold,
        message=message[:500],
        source=source,
        dedupe_key=dedupe_key,
        created_at=now,
    )
    session.add(event)
    alert.triggered_at = now
    alert.dismissed_at = None
    if bar_date is not None:
        alert.last_fired_bar_date = bar_date
    session.add(alert)
    session.flush()
    from stockviz.services.alerts import on_alert_fired

    on_alert_fired(session, alert, event)
    return event


def evaluate_pending_alerts(
    session: Session,
    *,
    ticker: str | None = None,
    commit: bool = True,
    now: datetime | None = None,
) -> int:
    """Judge every active price and technical rule on its newest bar.

    ``ticker`` limits the pass to one symbol (the event-driven worker).
    Returns the number of firings written.
    """
    now = now or utcnow()
    session_date = latest_completed_session(now.replace(tzinfo=UTC))
    rules = _active_rules(session, ticker)
    bars_cache: dict[tuple[str, int], list[PriceBar]] = {}
    fired = 0
    for alert in rules:
        assert alert.ticker is not None
        limit = _bars_needed(alert)
        key = (alert.ticker, limit)
        if key not in bars_cache:
            bars_cache[key] = _bars(session, alert.ticker, limit)
        bars = bars_cache[key]
        try:
            points = (
                _technical_points(alert, bars)
                if alert.kind == AlertKind.TECHNICAL
                else _price_points(alert, bars)
            )
        except (KeyError, ValueError) as exc:  # a rule the registry no longer knows
            logger.warning("alert %s cannot be evaluated: %s", alert.id, exc)
            continue
        hit, point = _judge(alert, points, known_at_arming)
        session.add(alert)
        if hit and point is not None:
            event = fire(
                session,
                alert,
                session_date=session_date,
                bar_date=point.bar_date,
                observed=point.observed,
                threshold=point.threshold,
                message=_message(alert, point),
                source="bar",
                dedupe_key=f"{alert.id}:{point.bar_date.isoformat()}",
                now=now,
            )
            fired += event is not None
    if commit:
        session.commit()
    return fired
