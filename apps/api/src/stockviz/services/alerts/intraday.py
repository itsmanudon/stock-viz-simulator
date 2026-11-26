"""Rule alerts on intraday timeframes (A6.4, M4.5 intraday).

A ``rule`` alert whose setup version has an intraday ``timeframe`` is judged
**once per closed bar** of that timeframe, never per day:

- **State per bar instant.** ``alerts.last_bar_at`` is the open of the last
  bar judged (naive UTC) and ``last_state`` the rule's value there;
  ``last_fired_bar_at`` the bar of the last firing. A bar at or before
  ``last_bar_at`` is skipped, so judging the same stored bars again, or a
  restarted stream worker, never fires twice.
- **Closed bars only.** A bar is judged once its ``closed_at`` has passed
  (``load_symbol_intraday`` leaves a partial newest bar out), in point mode
  (``dsl.point``: the data cut at that bar), so a live stream and the stored
  bars give the same answer (the conformance suite proves point = vector).
- **Same rules as the daily alerts.** It fires when the rule goes from not
  true to true; ``unknown`` never fires and counts as not true. Never judged
  before, its starting state is the newest bar closed by ``armed_at`` (a bar
  the user could already see arms only). ``once`` stops after a firing;
  ``every_cross`` waits ``cooldown_sessions`` **bars of the rule's
  timeframe**.
- **Dedupe per (alert, bar).** The event's key is ``<alert>:<bar open, UTC,
  ISO minutes>Z``, unique in ``alert_events``; the event carries ``bar_at``
  and ``feed``, and its text names the timeframe, the bar's time in the
  venue's zone and the feed's badge.

:func:`judge_bar` takes one bar (A6.5's stream worker calls it as each bar
closes); :func:`evaluate_intraday_alerts` runs it over stored bars from an
instant on (``stockviz.cli evaluate-alerts --intraday --since``, local use;
not in the cron). The nightly end-of-day judgement is unchanged and skips
these alerts.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

import numpy as np
from sqlmodel import Session, col, or_, select

from stockviz._time import utcnow
from stockviz.models import Alert, AlertEvent, AlertKind, AlertRepeat
from stockviz.models.setup import SetupVersion
from stockviz.services.bars.intraday import FEED_BADGES, NoIntradayData
from stockviz.services.dsl import CompiledRule, RuleError, SymbolData, point
from stockviz.services.dsl.data import instant, load_symbol_intraday
from stockviz.services.markets.calendar import venue_zone

logger = logging.getLogger(__name__)


def _naive(when: datetime) -> datetime:
    return instant(when).to_pydatetime()


def dedupe_key(alert: Alert, bar_at: datetime) -> str:
    return f"{alert.id}:{_naive(bar_at):%Y-%m-%dT%H:%M}Z"


def feed_label(feed: str | None) -> str:
    """How a firing names its source. ``replayed`` (A6.5's SimulatedFeed)
    says so and is never called live."""
    if feed == "replayed":
        return "Replayed from stored bars, not live"
    return FEED_BADGES.get(feed or "", feed or "unknown feed")


def message(alert: Alert, data: SymbolData, i: int) -> str:
    p = alert.params or {}
    name = p.get("setup_name") or "Your rule"
    version = f" (v{p['version']})" if p.get("version") else ""
    canonical = p.get("canonical") or ""
    closed = datetime.fromtimestamp(int(data.closed_at[i]) / 1e9, UTC)  # type: ignore[index]
    local = closed.astimezone(venue_zone(data.venue))
    return (
        f"{alert.ticker} {data.timeframe}: {name}{version} became true on the bar closing at "
        f"{local:%H:%M %Z} on {local:%Y-%m-%d}, {feed_label(data.feed)}: {canonical}"
    )[:500]


@dataclass(frozen=True)
class Judged:
    bar_at: datetime
    state: bool
    fired: AlertEvent | None


def _bar_index(data: SymbolData, bar_at: datetime) -> int:
    ts = instant(bar_at)
    i = int(data.bars.index.searchsorted(ts.to_datetime64()))
    if i >= len(data.bars) or data.bars.index[i] != ts:
        raise ValueError(f"{data.ticker} has no {data.timeframe} bar at {ts}")
    return i


def _armed_index(alert: Alert, data: SymbolData) -> int:
    """The newest bar closed when the rule was armed (-1: none loaded)."""
    armed = _naive(alert.armed_at or alert.created_at)
    cutoff = int(instant(armed).value)
    assert data.closed_at is not None
    return int(np.searchsorted(data.closed_at, cutoff, side="right")) - 1


def judge_bar(
    session: Session,
    alert: Alert,
    rule: CompiledRule,
    data: SymbolData,
    bar_at: datetime,
    *,
    now: datetime | None = None,
) -> Judged | None:
    """Judge ``alert`` on the closed bar opening at ``bar_at``. ``data`` holds
    that bar (and the warm-up before it; later bars are ignored: point mode
    cuts at the bar). None when the bar was judged already or is not closed
    at ``now``. Mutates the alert's state; no commit."""
    now = now or utcnow()
    now_ns = int(instant(now).value)
    i = _bar_index(data, bar_at)
    assert data.closed_at is not None
    bar = _naive(bar_at)
    if int(data.closed_at[i]) > now_ns:
        return None  # not closed yet
    if alert.last_bar_at is not None and bar <= alert.last_bar_at:
        return None  # judged already
    current = point(rule, data, bar) is True  # unknown counts as not true
    if alert.last_state is None:
        armed = _armed_index(alert, data)
        if i <= armed:
            hit = False  # the user could already see this bar: arm only
        else:
            prior = armed >= 0 and point(rule, data, data.instants[armed]) is True
            hit = current and not prior
    else:
        hit = current and not alert.last_state
    if hit and alert.repeat == AlertRepeat.EVERY_CROSS and alert.last_fired_bar_at is not None:
        fired_at = instant(alert.last_fired_bar_at)
        if fired_at >= data.bars.index[0]:
            since = int(((data.bars.index > fired_at) & (data.bars.index <= instant(bar))).sum())
            if since < alert.cooldown_sessions:
                hit = False
    alert.last_state = current
    alert.last_bar_at = bar
    session.add(alert)
    event = None
    if hit:
        from stockviz.services.alerts.engine import fire

        event = fire(
            session,
            alert,
            session_date=data.dates[i],
            bar_date=data.dates[i],
            observed=None,
            threshold=None,
            message=message(alert, data, i),
            source="bar",
            dedupe_key=dedupe_key(alert, bar),
            now=now if now.tzinfo is None else now.astimezone(UTC).replace(tzinfo=None),
            bar_at=bar,
            feed=data.feed,
        )
    return Judged(bar, current, event)


def intraday_alerts(
    session: Session, ticker: str | None = None
) -> list[tuple[Alert, SetupVersion]]:
    """Active rule alerts whose version is on an intraday timeframe."""
    from stockviz.services.instruments import instrument_of

    stmt = (
        select(Alert, SetupVersion)
        .join(SetupVersion, col(SetupVersion.id) == col(Alert.setup_version_id))
        .where(
            col(Alert.paused).is_(False),
            col(Alert.kind) == AlertKind.RULE,
            col(SetupVersion.timeframe) != "daily",
            or_(col(Alert.repeat) == AlertRepeat.EVERY_CROSS, col(Alert.triggered_at).is_(None)),
        )
        .order_by(col(Alert.id))
    )
    if ticker is not None:
        stmt = stmt.where(Alert.instrument_id == instrument_of(ticker))
    return [(a, v) for a, v in session.exec(stmt).all()]


@dataclass
class IntradayRun:
    alerts: int = 0
    bars: int = 0
    fired: int = 0
    skipped: list[str] | None = None
    events: list[AlertEvent] | None = None


def evaluate_intraday_alerts(
    session: Session,
    *,
    since: datetime,
    ticker: str | None = None,
    now: datetime | None = None,
    commit: bool = True,
) -> IntradayRun:
    """Judge every active intraday rule alert on each closed stored bar that
    opens at or after ``since`` (naive = UTC), oldest first, as a stream
    would. Bars already judged are skipped, so a rerun fires nothing twice."""
    from stockviz.services.dsl import compile_rule

    now = now or datetime.now(UTC)
    run = IntradayRun(skipped=[], events=[])
    since = _naive(since)
    for alert, version in intraday_alerts(session, ticker):
        assert alert.ticker is not None and run.skipped is not None and run.events is not None
        if alert.repeat == AlertRepeat.ONCE and alert.triggered_at is not None:
            continue
        try:
            rule = compile_rule(version.rule_text, timeframe=version.timeframe)
        except RuleError as exc:
            logger.warning("intraday alert %s: version %s no longer compiles: %s",
                           alert.id, version.id, exc)  # fmt: skip
            run.skipped.append(f"alert {alert.id}: its rule no longer compiles")
            continue
        start = since
        if alert.last_state is None:
            start = min(start, _naive(alert.armed_at or alert.created_at))
        if alert.last_fired_bar_at is not None:
            start = min(start, alert.last_fired_bar_at)
        try:
            data = load_symbol_intraday(
                session, alert.ticker, timeframe=version.timeframe, end=_naive(now),
                start=start, lookback=rule.lookback,
                feed=None if version.feed == "auto" else version.feed,
                needs=rule.needs, user_id=alert.user_id, now=now,
            )  # fmt: skip
        except NoIntradayData as exc:
            run.skipped.append(f"alert {alert.id}: {exc}")
            continue
        run.alerts += 1
        for bar_at in data.instants:
            if bar_at < since:
                continue
            judged = judge_bar(session, alert, rule, data, bar_at, now=now)
            if judged is None:
                continue
            run.bars += 1
            if judged.fired is not None:
                run.fired += 1
                run.events.append(judged.fired)
                if alert.repeat == AlertRepeat.ONCE:
                    break
    if commit:
        session.commit()
    else:
        session.flush()
    return run


__all__ = [
    "IntradayRun",
    "Judged",
    "dedupe_key",
    "evaluate_intraday_alerts",
    "feed_label",
    "intraday_alerts",
    "judge_bar",
    "message",
]
