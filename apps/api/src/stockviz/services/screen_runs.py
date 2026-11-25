"""Nightly screen runs and their entry/exit diffs (A2.3, M4.5).

``run_screen_runs`` (the ``screen-runs`` job) takes every setup version a
saved screen points at, judges its rule over the whole active universe with
``services/screener_rule.py`` (each venue on its latest completed session,
exactly as ``GET /v1/screener?setup_version_id=`` with no filters), and
stores the members in ``screen_runs``:

- One row per (setup version, session date). The session date is the job's
  New York session (``latest_completed_session``, as every nightly job);
  ``sessions`` keeps the session each venue was judged on. A rerun of the
  night replaces the row.
- Members are the instrument ids whose rule was ``met``. ``unknown``
  results are counted in ``not_evaluated`` and are never members, so a
  symbol whose data went missing does not "exit".

Then each run is compared with the version's previous stored run (the
newest earlier session date). Entries and exits become one notification per
saved screen with ``notify_on_change`` (category ``screen``, ``source_key``
``<screen id>:<session date>``, so a rerun adds nothing). The diff keeps
the screen's market, exchange and currency filters (its other filters are
the snapshot's and are not applied here). A version's first run records
state only.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from urllib.parse import parse_qs

from sqlmodel import Session, col, select

from stockviz import _time
from stockviz.models import (
    Instrument,
    InstrumentIdentifier,
    NotificationCategory,
    SavedScreen,
    ScreenRun,
    Setup,
    SetupVersion,
    Symbol,
)
from stockviz.services.backtest.universe import screen_universe
from stockviz.services.dsl import RuleError, compile_rule
from stockviz.services.instruments import instrument_ids, is_index_ticker
from stockviz.services.markets.calendar import latest_completed_session
from stockviz.services.notifications import notify
from stockviz.services.screener_rule import evaluate_rule

logger = logging.getLogger(__name__)

MAX_LISTED = 25
"""Tickers named in a notification's body; ``data`` holds them all."""


@dataclass
class ScreenRunsResult:
    session_date: date
    versions: int = 0
    runs: int = 0
    notifications: int = 0
    failed: list[int] = field(default_factory=list)


def _universe(session: Session) -> list[str]:
    tickers = session.exec(select(Symbol.ticker).where(col(Symbol.is_active))).all()
    return sorted(t for t in tickers if not is_index_ticker(t))


def _tickers_of(session: Session, ids: set[int]) -> dict[int, str]:
    if not ids:
        return {}
    rows = session.exec(
        select(InstrumentIdentifier.instrument_id, InstrumentIdentifier.value).where(
            col(InstrumentIdentifier.instrument_id).in_(sorted(ids)),
            InstrumentIdentifier.scheme == "yahoo",
            col(InstrumentIdentifier.valid_to).is_(None),
        )
    ).all()
    return {int(i): str(v) for i, v in rows}


def _filters(query: str) -> tuple[set[str], set[str], set[str]]:
    q = parse_qs(query.lstrip("?"))

    def values(name: str) -> set[str]:
        return {p.strip().upper() for raw in q.get(name, []) for p in raw.split(",") if p.strip()}

    return values("market"), values("exchange"), values("currency")


def _keep(session: Session, ids: set[int], query: str) -> set[int]:
    markets, exchanges, currencies = _filters(query)
    if not ids or not (markets or exchanges or currencies):
        return ids
    rows = session.exec(
        select(Instrument.id, Instrument.country, Instrument.mic, Instrument.currency).where(
            col(Instrument.id).in_(sorted(ids))
        )
    ).all()
    kept = set()
    for iid, country, mic, ccy in rows:
        if markets and (country or "").upper() not in markets:
            continue
        if exchanges and (mic or "").upper() not in exchanges:
            continue
        if currencies and (ccy or "").upper() not in currencies:
            continue
        if iid is not None:
            kept.add(int(iid))
    return kept


def _store(
    session: Session,
    version_id: int,
    session_date: date,
    members: list[int],
    evaluated: int,
    not_evaluated: int,
    sessions: dict[str, str],
    now: datetime,
) -> ScreenRun:
    row = session.exec(
        select(ScreenRun).where(
            ScreenRun.setup_version_id == version_id, ScreenRun.session_date == session_date
        )
    ).first()
    if row is None:
        row = ScreenRun(setup_version_id=version_id, session_date=session_date, universe="")
    row.venue = "all"
    row.universe = screen_universe().name
    row.members = members
    row.member_count = len(members)
    row.evaluated = evaluated
    row.not_evaluated = not_evaluated
    row.sessions = sessions
    row.computed_at = now
    session.add(row)
    return row


def _previous(session: Session, version_id: int, session_date: date) -> ScreenRun | None:
    return session.exec(
        select(ScreenRun)
        .where(ScreenRun.setup_version_id == version_id, ScreenRun.session_date < session_date)
        .order_by(col(ScreenRun.session_date).desc())
    ).first()


def _listed(tickers: list[str]) -> str:
    shown = ", ".join(tickers[:MAX_LISTED])
    more = len(tickers) - MAX_LISTED
    return shown + (f" and {more} more" if more > 0 else "")


def _notify_screen(
    session: Session,
    screen: SavedScreen,
    version: SetupVersion,
    setup_name: str,
    session_date: date,
    entries: list[str],
    exits: list[str],
) -> bool:
    assert screen.id is not None
    parts = []
    if entries:
        parts.append(f"Entered ({len(entries)}): {_listed(entries)}.")
    if exits:
        parts.append(f"Left ({len(exits)}): {_listed(exits)}.")
    title = f"{screen.name}: {len(entries)} in, {len(exits)} out on {session_date.isoformat()}"
    row = notify(
        session,
        user_id=screen.user_id,
        category=NotificationCategory.SCREEN,
        title=title,
        body=" ".join(parts) + f" Rule: {setup_name} v{version.version}.",
        link=f"/screener?{screen.query}" if screen.query else "/screener",
        source_key=f"{screen.id}:{session_date.isoformat()}",
        data={
            "screen_id": screen.id,
            "screen_name": screen.name,
            "setup_version_id": version.id,
            "session_date": session_date.isoformat(),
            "entries": entries,
            "exits": exits,
        },
    )
    return row is not None


def run_screen_runs(session: Session, *, now: datetime | None = None) -> ScreenRunsResult:
    """Store tonight's members for every screened setup version and notify diffs."""
    now = now or _time.utcnow()
    aware = now.replace(tzinfo=UTC) if now.tzinfo is None else now
    session_date = latest_completed_session(aware)
    result = ScreenRunsResult(session_date=session_date)
    screens = session.exec(
        select(SavedScreen)
        .where(col(SavedScreen.setup_version_id).is_not(None))
        .order_by(col(SavedScreen.id))
    ).all()
    by_version: dict[int, list[SavedScreen]] = {}
    for screen in screens:
        assert screen.setup_version_id is not None
        by_version.setdefault(screen.setup_version_id, []).append(screen)
    result.versions = len(by_version)
    if not by_version:
        return result
    tickers = _universe(session)
    ids = instrument_ids(session, tickers)
    for version_id, watchers in sorted(by_version.items()):
        version = session.get(SetupVersion, version_id)
        if version is None:
            continue
        try:
            rule = compile_rule(version.rule_text)
        except RuleError as exc:
            # A version saved under an older grammar: logged, not a failed night.
            logger.warning("screen-runs: version %s does not compile: %s", version_id, exc)
            continue
        # A3.3: a rule that reads drawings reads its setup owner's (only the
        # owner's own screens can point at it).
        owner = None
        if rule.user_scoped:
            setup_row = session.get(Setup, version.setup_id)
            owner = setup_row.user_id if setup_row is not None else None
        try:
            run = evaluate_rule(
                session, rule, tickers, as_of=None, now=aware, use_cache=False, user_id=owner
            )
        except Exception:  # one bad version never stops the rest
            logger.exception("screen-runs: version %s failed", version_id)
            session.rollback()
            result.failed.append(version_id)
            continue
        met = sorted(ids[t] for t, r in run.results.items() if r.status == "met" and t in ids)
        unknown = sum(1 for r in run.results.values() if r.status == "unknown")
        previous = _previous(session, version_id, session_date)
        _store(
            session, version_id, session_date, met, len(run.results), unknown,
            {venue: day.isoformat() for venue, day in run.sessions.items()}, now,
        )  # fmt: skip
        result.runs += 1
        if previous is not None:
            before, after = set(previous.members or []), set(met)
            setup = session.get(Setup, version.setup_id)
            name = setup.name if setup is not None else "rule"
            names = _tickers_of(session, before ^ after)
            for screen in watchers:
                if not screen.notify_on_change:
                    continue
                entered = _keep(session, after - before, screen.query)
                left = _keep(session, before - after, screen.query)
                entries = sorted(names.get(i, f"#{i}") for i in entered)
                exits = sorted(names.get(i, f"#{i}") for i in left)
                if (entries or exits) and _notify_screen(
                    session, screen, version, name, session_date, entries, exits
                ):
                    result.notifications += 1
        session.commit()
    return result


__all__ = ["ScreenRunsResult", "run_screen_runs"]
