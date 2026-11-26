"""Journal entries (A5.5, M10.3): round trips across paper, imported and replay.

``journal_entries`` stores the grouping and the user's text only
(``models/journal_entry.py``); every figure is computed here on read from
the fills, the stored daily bars and the plan (``roundtrips.py`` holds the
pure rules).

**Following the fills.** ``collect`` regroups every fill of the user's books
(``trades``, the ledger of paper and imported books alike: an imported book
rebuilds its trades on every commit, delete, opening lot and split) and
replay sessions (``replay_fills``), and ``sync`` matches each round trip to
its row by ``entry_key``. Reads call ``sync`` first, so an import commit or
delete is followed on the next read, with nothing to invalidate.

**Plans.** A paper or imported entry's plan is the one its fills link
(``trades.trade_plan_id``: A5.4 links it at the ticket, A5.3 at the import,
locking a plan written before the fill). A replay session's plan pairs with
the session's first round trip, the one its lock describes.

**Dates.** A fill's date is its venue's date (``venue_for_ticker``: IST for
NSE and BSE), never New York's.

**News at entry and exit.** Aegis documents linked to the instrument with
``available_at`` from the start of the third session before the entry day
to the end of the entry day, and from the session before the exit day to
the end of the session after it, in the venue's time zone: headline, source,
time and link only. A replay entry never sees a document after the session's
clock. A window ending before the first document held says "no news copy for
this date", not "no news".
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

from sqlmodel import Session, col, func, select

from stockviz._time import utcnow
from stockviz.models import (
    AegisDocument,
    BrokerFill,
    Instrument,
    Portfolio,
    PriceBar,
    ReplayFill,
    ReplaySession,
    Setup,
    SetupVersion,
    Trade,
    User,
)
from stockviz.models.journal_entry import (
    MAX_ENTRY_TAG_LENGTH,
    MAX_ENTRY_TAGS,
    JournalEntry,
    JournalEntryFill,
)
from stockviz.models.trade_plan import TradePlan
from stockviz.schemas import (
    JournalEntryFillOut,
    JournalEntryOut,
    JournalEntryPatch,
    JournalEntryPlanOut,
    JournalEntrySummaryOut,
    JournalExcursionOut,
    JournalExcursionsOut,
    JournalNewsHeadlineOut,
    JournalNewsWindowOut,
)
from stockviz.services.drills.score import BarFacts, FillFacts, PlanFacts, score_drill
from stockviz.services.journal.roundtrips import (
    Bar,
    Excursion,
    Excursions,
    LedgerFill,
    RoundTrip,
    TradeFigures,
    excursions,
    group_round_trips,
    r_multiple,
    trade_figures,
)
from stockviz.services.markets.calendar import (
    is_session,
    previous_session,
    venue_for_ticker,
    venue_zone,
)
from stockviz.services.plans import hidden_drill_session_ids
from stockviz.services.symbol_events import linked_document_ids
from stockviz.services.theses import tickers_for
from stockviz.services.trading.books import resolve_book, user_books

ZERO = Decimal(0)
NEWS_BEFORE_SESSIONS = 3
NEWS_PER_WINDOW = 20
LIST_NOTE = (
    "One row per round trip, flat to flat (partial exits stay in it). The P&L calendar "
    "below counts each closing fill on its own day."
)
WRITTEN_AFTER_NOTE = "The plan was written after entry: shown, but not counted in plan adherence."


class JournalEntryNotFound(Exception):
    """No such entry for this user (404)."""


class JournalEntryError(Exception):
    """A patch the entry cannot take (422)."""


# --- collecting the round trips ----------------------------------------------------


@dataclass
class Trip:
    """A round trip with where it lives."""

    trip: RoundTrip
    source: str  # paper | imported | replay
    instrument_id: int
    ticker: str | None
    currency: str
    venue: str
    portfolio_id: int | None = None
    replay: ReplaySession | None = None
    plan_id: int | None = None
    row: JournalEntry | None = field(default=None, repr=False)

    @property
    def key(self) -> str:
        return self.trip.key


def _venue_date(ts: datetime, venue: str) -> date:
    aware = ts.replace(tzinfo=UTC) if ts.tzinfo is None else ts
    return aware.astimezone(venue_zone(venue)).date()


def venue_session_date(ts: datetime, ticker: str) -> date:
    """The venue date of a naive-UTC fill time (IST for ``.NS``/``.BO``)."""
    return _venue_date(ts, venue_for_ticker(ticker))


def _instrument_facts(
    session: Session, instrument_ids: Iterable[int]
) -> tuple[dict[int, str], dict[int, str]]:
    ids = sorted(set(instrument_ids))
    if not ids:
        return {}, {}
    tickers = tickers_for(session, ids)
    currencies = {
        iid: cur or "USD"
        for iid, cur in session.exec(
            select(Instrument.id, Instrument.currency).where(col(Instrument.id).in_(ids))
        ).all()
        if iid is not None
    }
    return tickers, currencies


def _book_trips(
    session: Session,
    books: list[Portfolio],
    *,
    instrument_id: int | None = None,
) -> list[Trip]:
    book_ids = [b.id for b in books if b.id is not None]
    if not book_ids:
        return []
    kinds = {b.id: b.kind for b in books}
    stmt = (
        select(Trade, BrokerFill)
        .join(BrokerFill, col(BrokerFill.id) == col(Trade.broker_fill_id), isouter=True)
        .where(col(Trade.portfolio_id).in_(book_ids))
    )
    if instrument_id is not None:
        stmt = stmt.where(col(Trade.instrument_id) == instrument_id)
    rows = session.exec(
        stmt.order_by(
            col(Trade.portfolio_id), col(Trade.instrument_id), col(Trade.ts), col(Trade.id)
        )
    ).all()
    tickers, currencies = _instrument_facts(
        session, (t.instrument_id for t, _ in rows if t.instrument_id is not None)
    )
    groups: dict[tuple[int, int], list[LedgerFill]] = {}
    for trade, broker in rows:
        if trade.instrument_id is None or trade.id is None:
            continue
        ticker = tickers.get(trade.instrument_id) or trade.ticker
        venue = venue_for_ticker(ticker)
        if broker is not None:
            if broker.kind == "opening":
                key = f"imported:{trade.portfolio_id}:opening:{broker.id}"
            else:
                key = (
                    f"imported:{trade.portfolio_id}:{broker.broker}:{broker.exchange}:"
                    f"{broker.trade_id}"
                )
        else:
            key = f"{kinds.get(trade.portfolio_id, 'paper')}:{trade.portfolio_id}:t{trade.id}"
        groups.setdefault((trade.portfolio_id, trade.instrument_id), []).append(
            LedgerFill(
                key=key,
                side=str(getattr(trade.side, "value", trade.side)).lower(),
                quantity=trade.quantity,
                price=trade.price,
                fees=trade.fees or ZERO,
                at=trade.ts,
                venue_date=_venue_date(trade.ts, venue),
                trade_id=trade.id,
                plan_id=trade.trade_plan_id,
                time_known=broker.time_known if broker is not None else True,
                fees_estimated=broker is not None,
            )
        )
    out: list[Trip] = []
    for (pid, iid), fills in groups.items():
        ticker = tickers.get(iid)
        venue = venue_for_ticker(ticker or "")
        source = "imported" if kinds.get(pid) == "imported" else "paper"
        for trip in group_round_trips(fills):
            plan_id = next((f.plan_id for f in trip.fills if f.plan_id is not None), None)
            out.append(
                Trip(
                    trip=trip,
                    source=source,
                    instrument_id=iid,
                    ticker=ticker,
                    currency=currencies.get(iid, "USD"),
                    venue=venue,
                    portfolio_id=pid,
                    plan_id=plan_id,
                )
            )
    return out


def _replay_trips(session: Session, user_id: int) -> list[Trip]:
    hidden = hidden_drill_session_ids(session, user_id)
    replays = [
        r
        for r in session.exec(
            select(ReplaySession).where(col(ReplaySession.user_id) == user_id)
        ).all()
        if r.id is not None and r.id not in hidden and r.instrument_id is not None
    ]
    if not replays:
        return []
    by_id = {r.id: r for r in replays}
    fills = session.exec(
        select(ReplayFill)
        .where(col(ReplayFill.session_id).in_(sorted(by_id)))
        .order_by(col(ReplayFill.session_id), col(ReplayFill.evaluated_at), col(ReplayFill.id))
    ).all()
    plans = {
        p.replay_session_id: p
        for p in session.exec(
            select(TradePlan).where(col(TradePlan.replay_session_id).in_(sorted(by_id)))
        ).all()
    }
    _tickers, currencies = _instrument_facts(
        session, (r.instrument_id for r in replays if r.instrument_id is not None)
    )
    grouped: dict[int, list[LedgerFill]] = {}
    for fill in fills:
        assert fill.id is not None
        grouped.setdefault(fill.session_id, []).append(
            LedgerFill(
                key=f"replay:{fill.session_id}:f{fill.id}",
                side=fill.side.lower(),
                quantity=fill.quantity,
                price=fill.fill_price,
                fees=fill.fees or ZERO,
                at=fill.evaluated_at,
                venue_date=fill.evaluated_at.date(),
                replay_fill_id=fill.id,
            )
        )
    out: list[Trip] = []
    for sid, ledger in grouped.items():
        replay = by_id[sid]
        assert replay.instrument_id is not None
        plan = plans.get(sid)
        for index, trip in enumerate(group_round_trips(ledger)):
            paired = plan is not None and plan.first_fill_at is not None and index == 0
            out.append(
                Trip(
                    trip=trip,
                    source="replay",
                    instrument_id=replay.instrument_id,
                    ticker=replay.ticker,
                    currency=currencies.get(replay.instrument_id, replay.currency or "USD"),
                    venue=venue_for_ticker(replay.ticker),
                    replay=replay,
                    plan_id=plan.id if paired and plan is not None else None,
                )
            )
    return out


def collect(session: Session, user_id: int) -> list[Trip]:
    """Every round trip of the user's books and visible replay sessions."""
    return _book_trips(session, user_books(session, user_id)) + _replay_trips(session, user_id)


# --- the sync -----------------------------------------------------------------------


def sync(session: Session, user_id: int) -> list[Trip]:
    """Match the round trips to their rows; write only what changed.

    A row whose round trip is gone is deleted, unless it holds the user's text:
    then it is kept as ``detached`` (hidden) and found again if the same first
    fill comes back (an import deleted and committed again).
    """
    # One sync per user at a time (PostgreSQL; SQLite ignores the lock).
    session.exec(select(User.id).where(col(User.id) == user_id).with_for_update()).first()
    trips = collect(session, user_id)
    rows = {
        r.entry_key: r
        for r in session.exec(
            select(JournalEntry).where(col(JournalEntry.user_id) == user_id)
        ).all()
    }
    links: dict[int, set[tuple[int | None, int | None]]] = {}
    for link, entry_id in session.exec(
        select(JournalEntryFill, JournalEntry.id)
        .join(JournalEntry, col(JournalEntry.id) == col(JournalEntryFill.entry_id))
        .where(col(JournalEntry.user_id) == user_id)
    ).all():
        assert entry_id is not None
        links.setdefault(entry_id, set()).add((link.trade_id, link.replay_fill_id))

    changed = False
    now = utcnow()
    wanted: dict[int, set[tuple[int | None, int | None]]] = {}
    seen: set[str] = set()
    for t in trips:
        seen.add(t.key)
        status = "closed" if t.trip.closed else "open"
        row = rows.get(t.key)
        fields = {
            "source": t.source,
            "portfolio_id": t.portfolio_id,
            "replay_session_id": t.replay.id if t.replay is not None else None,
            "instrument_id": t.instrument_id,
            "plan_id": t.plan_id,
            "status": status,
            "opened_at": t.trip.opened_at,
            "closed_at": t.trip.closed_at,
        }
        if row is None:
            row = JournalEntry(
                user_id=user_id, entry_key=t.key, created_at=now, updated_at=now, **fields
            )  # type: ignore[arg-type]
            session.add(row)
            rows[t.key] = row
            changed = True
        elif any(getattr(row, k) != v for k, v in fields.items()):
            for k, v in fields.items():
                setattr(row, k, v)
            session.add(row)
            changed = True
        t.row = row
    for key, row in rows.items():
        if key in seen:
            continue
        if row.has_text:
            if row.status != "detached":
                row.status = "detached"
                session.add(row)
                changed = True
        else:
            session.delete(row)
            changed = True
    if changed:
        session.flush()
    for t in trips:
        assert t.row is not None and t.row.id is not None
        wanted[t.row.id] = {(f.trade_id, f.replay_fill_id) for f in t.trip.fills}
    stale = [eid for eid, want in wanted.items() if links.get(eid, set()) != want]
    stale += [eid for eid in links if eid not in wanted]
    if stale:
        for link in session.exec(
            select(JournalEntryFill).where(col(JournalEntryFill.entry_id).in_(stale))
        ).all():
            session.delete(link)
        session.flush()
        for eid in stale:
            for trade_id, replay_fill_id in wanted.get(eid, set()):
                session.add(
                    JournalEntryFill(entry_id=eid, trade_id=trade_id, replay_fill_id=replay_fill_id)
                )
        changed = True
    if changed:
        session.commit()
    return trips


# --- reading --------------------------------------------------------------------------


@dataclass
class Filters:
    book_id: int | None = None
    status: str | None = None
    source: str | None = None
    setup_version_id: int | None = None
    tag: str | None = None
    ticker: str | None = None
    date_from: date | None = None
    date_to: date | None = None


def list_entries(
    session: Session, user_id: int, filters: Filters, *, limit: int, offset: int
) -> tuple[list[JournalEntrySummaryOut], int]:
    book = resolve_book(session, user_id, filters.book_id) if filters.book_id else None
    trips = sync(session, user_id)
    plans = _plans(session, [t.plan_id for t in trips if t.plan_id is not None])
    tag = filters.tag.strip().lower() if filters.tag else None
    ticker = filters.ticker.strip().upper() if filters.ticker else None

    def keep(t: Trip) -> bool:
        assert t.row is not None
        if book is not None and t.portfolio_id != book.id:
            return False
        if filters.status and ("closed" if t.trip.closed else "open") != filters.status:
            return False
        if filters.source and t.source != filters.source:
            return False
        if filters.setup_version_id is not None:
            plan = plans.get(t.plan_id) if t.plan_id else None
            if plan is None or plan.setup_version_id != filters.setup_version_id:
                return False
        if tag and tag not in {x.lower() for x in (*t.row.setup_tags, *t.row.mistake_tags)}:
            return False
        if ticker and (t.ticker or "").upper() != ticker:
            return False
        day = t.trip.fills[0].venue_date
        if filters.date_from and day < filters.date_from:
            return False
        return not (filters.date_to and day > filters.date_to)

    kept = [t for t in trips if keep(t)]
    kept.sort(key=lambda t: (t.trip.opened_at, t.row.id if t.row else 0), reverse=True)
    page = kept[offset : offset + limit]
    labels = _setup_labels(session, plans.values())
    return [_summary(session, t, plans, labels) for t in page], len(kept)


def get_entry(session: Session, user_id: int, entry_id: int) -> JournalEntryOut:
    trip = _find(session, user_id, entry_id)
    plans = _plans(session, [trip.plan_id] if trip.plan_id else [])
    labels = _setup_labels(session, plans.values())
    return _detail(session, trip, plans, labels)


def patch_entry(
    session: Session, user_id: int, entry_id: int, body: JournalEntryPatch
) -> JournalEntryOut:
    trip = _find(session, user_id, entry_id)
    row = trip.row
    assert row is not None
    sent = body.model_fields_set
    for name in ("review_notes", "mistakes", "lessons"):
        if name in sent and getattr(body, name) is not None:
            value = getattr(body, name).strip()
            setattr(row, name, value or None)
    for name in ("setup_tags", "mistake_tags"):
        if name in sent and getattr(body, name) is not None:
            setattr(row, name, clean_tags(getattr(body, name)))
    row.updated_at = utcnow()
    session.add(row)
    session.commit()
    session.refresh(row)
    return get_entry(session, user_id, entry_id)


def clean_tags(tags: Iterable[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in tags:
        tag = " ".join(str(raw).split())
        if not tag:
            continue
        if len(tag) > MAX_ENTRY_TAG_LENGTH:
            raise JournalEntryError(f"A tag is at most {MAX_ENTRY_TAG_LENGTH} characters")
        if tag.lower() in seen:
            continue
        seen.add(tag.lower())
        out.append(tag)
    if len(out) > MAX_ENTRY_TAGS:
        raise JournalEntryError(f"At most {MAX_ENTRY_TAGS} tags")
    return out


def _find(session: Session, user_id: int, entry_id: int) -> Trip:
    row = session.get(JournalEntry, entry_id)
    if row is None or row.user_id != user_id:
        raise JournalEntryNotFound(f"Journal entry {entry_id} not found")
    for t in sync(session, user_id):
        if t.row is not None and t.row.id == entry_id:
            return t
    raise JournalEntryNotFound(f"Journal entry {entry_id} not found")


def _plans(session: Session, ids: Iterable[int]) -> dict[int, TradePlan]:
    wanted = sorted(set(ids))
    if not wanted:
        return {}
    return {
        p.id: p
        for p in session.exec(select(TradePlan).where(col(TradePlan.id).in_(wanted))).all()
        if p.id is not None
    }


def _setup_labels(session: Session, plans: Iterable[TradePlan]) -> dict[int, str]:
    ids = sorted({p.setup_version_id for p in plans if p.setup_version_id})
    if not ids:
        return {}
    labels: dict[int, str] = {}
    for vid, version, name in session.exec(
        select(SetupVersion.id, SetupVersion.version, Setup.name)
        .join(Setup, col(Setup.id) == col(SetupVersion.setup_id))
        .where(col(SetupVersion.id).in_(ids))
    ).all():
        if vid is not None:
            labels[vid] = f"{name} v{version}"
    return labels


@dataclass
class _Computed:
    bars: list[Bar]
    figures: TradeFigures
    excursions: Excursions
    r: float | None
    r_reason: str | None
    risk: Decimal | None
    end_day: date
    mark: Bar | None


def _bars(session: Session, t: Trip) -> list[Bar]:
    start = datetime.combine(t.trip.fills[0].venue_date, time.min)
    if t.replay is not None:
        stmt = select(PriceBar).where(
            col(PriceBar.instrument_id) == t.instrument_id,
            col(PriceBar.interval) == "1d",
            col(PriceBar.ts) >= max(start, t.replay.start_at),
            col(PriceBar.ts) <= t.replay.current_at,
            col(PriceBar.ts) <= t.replay.end_at,
        )
    else:
        stmt = select(PriceBar).where(
            col(PriceBar.instrument_id) == t.instrument_id,
            col(PriceBar.interval) == "1d",
            col(PriceBar.ts) >= start,
        )
        if t.trip.closed:
            last = t.trip.fills[-1].venue_date
            stmt = stmt.where(col(PriceBar.ts) <= datetime.combine(last, time.min))
    return [
        Bar(day=b.ts.date(), open=b.open, high=b.high, low=b.low, close=b.close)
        for b in session.exec(stmt.order_by(col(PriceBar.ts))).all()
    ]


def _expected_sessions(start: date, end: date, venue: str) -> list[date]:
    days: list[date] = []
    day = start
    while day <= end:
        if is_session(day, venue):
            days.append(day)
        day += timedelta(days=1)
    return days


def _compute(session: Session, t: Trip, plan: TradePlan | None) -> _Computed:
    bars = _bars(session, t)
    closed = t.trip.closed
    mark = None if closed or not bars else bars[-1]
    figures = trade_figures(t.trip, mark_close=mark.close if mark else None)
    rr = r_multiple(
        figures,
        stop=plan.planned_stop if plan else None,
        has_plan=plan is not None,
        open_without_mark=not closed and mark is None,
    )
    end_day = (
        t.trip.fills[-1].venue_date
        if closed
        else (mark.day if mark else t.trip.fills[-1].venue_date)
    )
    exact = t.source == "replay"
    exc = excursions(
        t.trip,
        bars,
        basis="exact_close" if exact else "approximate_daily",
        end_day=end_day,
        expected_sessions=None
        if exact
        else _expected_sessions(t.trip.fills[0].venue_date, end_day, t.venue),
        initial_risk=rr.initial_risk,
    )
    return _Computed(bars, figures, exc, rr.value, rr.reason, rr.initial_risk, end_day, mark)


def _excursion_out(e: Excursion | None) -> JournalExcursionOut | None:
    if e is None:
        return None
    return JournalExcursionOut(
        per_share=e.per_share, pct=e.pct, amount=e.amount, shares=e.shares, date=e.day,
        price=e.price, r=e.r,
    )  # fmt: skip


def _plan_out(plan: TradePlan | None, labels: dict[int, str]) -> JournalEntryPlanOut | None:
    if plan is None or plan.id is None:
        return None
    locked = plan.locked_at is not None and not plan.written_after_entry
    return JournalEntryPlanOut(
        id=plan.id,
        status=plan.status,
        label="locked" if locked else "written_after_entry",
        locked_at=plan.locked_at,
        first_fill_at=plan.first_fill_at,
        planned_entry=plan.planned_entry,
        planned_stop=plan.planned_stop,
        planned_target=plan.planned_target,
        planned_size=plan.planned_size,
        setup_version_id=plan.setup_version_id,
        setup_label=labels.get(plan.setup_version_id) if plan.setup_version_id else None,
        counts_for_adherence=locked,
    )


def _summary_fields(
    t: Trip, c: _Computed, plan: TradePlan | None, labels: dict[int, str]
) -> dict[str, object]:
    row = t.row
    assert row is not None and row.id is not None
    f = c.figures
    first, last = t.trip.fills[0], t.trip.fills[-1]
    exc = c.excursions
    return {
        "id": row.id,
        "source": t.source,
        "book_id": t.portfolio_id,
        "replay_session_id": t.replay.id if t.replay else None,
        "ticker": t.ticker,
        "currency": t.currency,
        "venue": t.venue,
        "status": "closed" if t.trip.closed else "open",
        "opened_at": t.trip.opened_at,
        "closed_at": t.trip.closed_at,
        "entry_date": first.venue_date,
        "exit_date": last.venue_date if t.trip.closed else None,
        "as_of_date": c.mark.day if c.mark else None,
        "mark_close": c.mark.close if c.mark else None,
        "avg_entry": f.avg_entry,
        "avg_exit": f.avg_exit,
        "quantity": f.peak_quantity,
        "held": f.held,
        "net_pnl": f.net_pnl,
        "realized_pnl": f.realized,
        "unrealized_pnl": f.unrealized,
        "fees": f.fees,
        "fees_estimated": f.fees_estimated,
        "return_pct": f.return_pct,
        "holding_days": (c.end_day - first.venue_date).days,
        "holding_sessions": len([b for b in c.bars if first.venue_date <= b.day <= c.end_day]),
        "fills_count": len(t.trip.fills),
        "r_multiple": c.r,
        "r_reason": c.r_reason,
        "initial_risk": c.risk,
        "excursions": JournalExcursionsOut(
            basis=exc.basis,
            note=exc.note,
            mae=_excursion_out(exc.mae),
            mfe=_excursion_out(exc.mfe),
            reason=exc.reason,
            missing_sessions=list(exc.missing_sessions),
            sessions=exc.sessions,
        ),
        "plan": _plan_out(plan, labels),
        "setup_tags": list(row.setup_tags or []),
        "mistake_tags": list(row.mistake_tags or []),
        "has_notes": bool(row.review_notes or row.mistakes or row.lessons),
    }


def _summary(
    session: Session, t: Trip, plans: dict[int, TradePlan], labels: dict[int, str]
) -> JournalEntrySummaryOut:
    plan = plans.get(t.plan_id) if t.plan_id else None
    return JournalEntrySummaryOut.model_validate(
        _summary_fields(t, _compute(session, t, plan), plan, labels)
    )


def _adherence(t: Trip, c: _Computed, plan: TradePlan | None):
    if plan is None:
        return None, None
    if plan.written_after_entry or plan.locked_at is None:
        return None, WRITTEN_AFTER_NOTE
    if plan.planned_entry is None or plan.planned_stop is None or plan.planned_size is None:
        return None, "The plan has no entry, stop or size, so adherence is not scored."
    score = score_drill(
        PlanFacts(entry=plan.planned_entry, stop=plan.planned_stop, size=plan.planned_size),
        [
            FillFacts(
                side=f.side,
                quantity=f.quantity,
                price=f.price,
                at=datetime.combine(f.venue_date, time.min),
            )
            for f in t.trip.fills
        ],
        [
            BarFacts(at=datetime.combine(b.day, time.min), close=b.close)
            for b in c.bars
            if b.day <= c.end_day
        ],
        total_pnl=c.figures.net_pnl,
    )
    note = None
    if t.source != "replay":
        note = "Checked on daily closes; the stop check reads each session's close."
    return score, note


def _detail(
    session: Session, t: Trip, plans: dict[int, TradePlan], labels: dict[int, str]
) -> JournalEntryOut:
    plan = plans.get(t.plan_id) if t.plan_id else None
    c = _compute(session, t, plan)
    fields = _summary_fields(t, c, plan, labels)
    score, note = _adherence(t, c, plan)
    row = t.row
    assert row is not None
    cap = t.replay.current_at if t.replay is not None else None
    entry_news = news_at_entry(session, t, cap=cap)
    exit_news = news_at_exit(session, t, cap=cap) if t.trip.closed else None
    return JournalEntryOut.model_validate(
        {
            **fields,
            "fills": [
                JournalEntryFillOut(
                    trade_id=f.trade_id,
                    replay_fill_id=f.replay_fill_id,
                    side=f.side,  # pyright: ignore[reportArgumentType]
                    quantity=f.quantity,
                    price=f.price,
                    fees=f.fees,
                    fees_estimated=f.fees_estimated,
                    at=f.at,
                    venue_date=f.venue_date,
                    time_known=f.time_known,
                )
                for f in t.trip.fills
            ],
            "adherence": score,
            "adherence_note": note,
            "news_at_entry": entry_news,
            "news_at_exit": exit_news,
            "review_notes": row.review_notes,
            "mistakes": row.mistakes,
            "lessons": row.lessons,
            "updated_at": row.updated_at,
        }
    )


# --- news at entry and exit ------------------------------------------------------------


def _next_session(day: date, venue: str) -> date:
    for ahead in range(1, 15):
        candidate = day + timedelta(days=ahead)
        if is_session(candidate, venue):
            return candidate
    return day + timedelta(days=1)


def _utc_bounds(first: date, last: date, venue: str) -> tuple[datetime, datetime]:
    zone = venue_zone(venue)
    lo = datetime.combine(first, time.min, tzinfo=zone).astimezone(UTC).replace(tzinfo=None)
    hi = (
        datetime.combine(last + timedelta(days=1), time.min, tzinfo=zone)
        .astimezone(UTC)
        .replace(tzinfo=None)
    )
    return lo, hi


def news_window(
    session: Session,
    *,
    ticker: str | None,
    venue: str,
    first: date,
    last: date,
    cap: datetime | None = None,
) -> JournalNewsWindowOut:
    lo, hi = _utc_bounds(first, last, venue)
    if cap is not None:
        hi = min(hi, cap + timedelta(microseconds=1))
    earliest = session.exec(select(func.min(AegisDocument.available_at))).one()
    if ticker is None or earliest is None or hi <= earliest:
        return JournalNewsWindowOut(
            from_date=first, to_date=last, coverage="before_news_copy",
            note="No news copy for this date: the news sync starts later.",
        )  # fmt: skip
    docs = session.exec(
        select(AegisDocument)
        .where(
            col(AegisDocument.document_id).in_(linked_document_ids(ticker)),
            col(AegisDocument.available_at) >= lo,
            col(AegisDocument.available_at) < hi,
        )
        .order_by(col(AegisDocument.available_at).desc(), col(AegisDocument.document_id))
        .limit(NEWS_PER_WINDOW)
    ).all()
    partial = lo < earliest
    note = (
        "Headlines available from the start of the window to its end, by when Aegis had them."
        if not partial
        else "The news sync starts inside this window: earlier days have no news copy."
    )
    return JournalNewsWindowOut(
        from_date=first,
        to_date=last,
        coverage="covered",
        note=note
        if docs
        else ("No headlines for this symbol in the window." if not partial else note),
        headlines=[
            JournalNewsHeadlineOut(
                id=d.document_id,
                title=d.title,
                source=d.source_name,
                url=d.url,
                available_at=d.available_at,
                date=_venue_date(d.available_at, venue),
            )
            for d in docs
        ],
    )


def news_at_entry(
    session: Session, t: Trip, *, cap: datetime | None = None
) -> JournalNewsWindowOut:
    day = t.trip.fills[0].venue_date
    first = day
    for _ in range(NEWS_BEFORE_SESSIONS):
        first = previous_session(first, t.venue)
    return news_window(session, ticker=t.ticker, venue=t.venue, first=first, last=day, cap=cap)


def news_at_exit(session: Session, t: Trip, *, cap: datetime | None = None) -> JournalNewsWindowOut:
    day = t.trip.fills[-1].venue_date
    return news_window(
        session,
        ticker=t.ticker,
        venue=t.venue,
        first=previous_session(day, t.venue),
        last=_next_session(day, t.venue),
        cap=cap,
    )


# --- R on the chart's fill markers -------------------------------------------------------


@dataclass(frozen=True)
class FillR:
    r_multiple: float | None
    journal_entry_id: int | None
    closes_entry: bool


def fill_r_multiples(
    session: Session, user_id: int, instrument_id: int, *, book_id: int | None = None
) -> dict[int, FillR]:
    """Per trade id: the entry's R on the fill that closes it; null on the others.

    Grouped over each book's whole history in the instrument (the window a
    chart asks for may start mid-entry). Read only: rows are not synced here,
    so ``journal_entry_id`` is known once the journal has been read.
    """
    books = user_books(session, user_id)
    if book_id is not None:
        books = [b for b in books if b.id == book_id]
    trips = _book_trips(session, books, instrument_id=instrument_id)
    plans = _plans(session, [t.plan_id for t in trips if t.plan_id is not None])
    trade_ids = [f.trade_id for t in trips for f in t.trip.fills if f.trade_id is not None]
    entry_of: dict[int, int] = {}
    if trade_ids:
        entry_of = {
            tid: eid
            for tid, eid in session.exec(
                select(JournalEntryFill.trade_id, JournalEntryFill.entry_id).where(
                    col(JournalEntryFill.trade_id).in_(trade_ids)
                )
            ).all()
            if tid is not None
        }
    out: dict[int, FillR] = {}
    for t in trips:
        closing = t.trip.closing_fill
        r_value: float | None = None
        if closing is not None:
            plan = plans.get(t.plan_id) if t.plan_id else None
            figures = trade_figures(t.trip)
            r_value = r_multiple(
                figures, stop=plan.planned_stop if plan else None, has_plan=plan is not None
            ).value
        for f in t.trip.fills:
            if f.trade_id is None:
                continue
            is_close = closing is not None and f is closing
            out[f.trade_id] = FillR(
                r_multiple=r_value if is_close else None,
                journal_entry_id=entry_of.get(f.trade_id),
                closes_entry=is_close,
            )
    return out


__all__ = [
    "LIST_NOTE",
    "WRITTEN_AFTER_NOTE",
    "FillR",
    "Filters",
    "JournalEntryError",
    "JournalEntryNotFound",
    "Trip",
    "clean_tags",
    "collect",
    "fill_r_multiples",
    "get_entry",
    "list_entries",
    "news_at_entry",
    "news_at_exit",
    "news_window",
    "patch_entry",
    "sync",
    "venue_session_date",
]
