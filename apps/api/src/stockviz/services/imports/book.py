"""Imports into an imported book (A5.3): preview, commit, rebuild, delete, opening lots.

**Protocol.** Two steps and nothing kept between them (design note, "Upload
path"; question 9):

1. ``preview`` parses the CSV, matches instruments and dedupes, then runs the
   ledger (``engine.replay_fills``) over the book's fills plus the new ones.
   It writes nothing, not even a token.
2. ``commit`` gets the same file again with the preview's ``file_sha256``; a
   different file is refused (409). It stores the new fills
   (``broker_fills``) and one ``import_batches`` row (hash and counts: no file,
   no file name, no client id), then rebuilds the book.

**Rebuild** is the one way an imported book's ledger changes: commit, batch
delete, opening lots and split rebases all call :func:`rebuild_book`, which
replays every fill of the book and rewrites its ``trades`` (one per posted
fill, ``broker_fill_id``) and ``positions``. Trade rows are updated in place,
so plan links survive a rebuild.

**Plans** (A5.4 rules, source ``imported``): a posted buy that opens a
position links the book's open plan for the instrument written before the
fill's time (``record_fill`` locks it at the fill), and later buys of the
same position join it. A plan written after the entry is linked by the
user (``POST /v1/plans`` with ``link_open_position``) and labelled so. A
position sold to zero closes its plan; a plan whose fills are all deleted
is closed and stays frozen (its lock is part of the record).

**Privacy.** Nothing here logs. Problems carry row numbers, fields and fixed
reasons; the parsed symbol is shown only where it is the problem
(unmatched).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import delete, func
from sqlmodel import Session, col, select

from stockviz._time import utcnow
from stockviz.models import (
    CorporateAction,
    Instrument,
    InstrumentIdentifier,
    Portfolio,
    Position,
    PriceBar,
    Symbol,
    Trade,
    TradeSide,
)
from stockviz.models.broker_import import (
    FEE_ESTIMATED,
    FILL_OPENING,
    FILL_TRADE,
    MAX_OPENING_LOTS_PER_BOOK,
    PRODUCT_DELIVERY,
    STATUS_NEEDS_OPENING_LOT,
    STATUS_POSTED,
    BrokerFill,
    ImportBatch,
)
from stockviz.models.instrument import SCHEME_ISIN, SCHEME_YAHOO
from stockviz.models.portfolio import BookKind
from stockviz.models.trade_plan import TradePlan
from stockviz.services.imports import columns
from stockviz.services.imports.engine import (
    DayRanges,
    FillOutcome,
    LedgerFill,
    LedgerResult,
    Splits,
    replay_fills,
)
from stockviz.services.imports.parse import (
    EQUITY_EXCHANGES,
    KIND_SEGMENT,
    MAX_FILE_BYTES,
    FileRejected,
    ParsedFile,
    ParsedRow,
    ist_day_start,
    parse_tradebook,
)
from stockviz.services.trading.books import resolve_book
from stockviz.services.trading.buying_power import lock_portfolio

SAMPLE_SIZE = 20
MAX_PROBLEMS = 300
MAX_COMMITS_PER_HOUR = 30
BROKER = "zerodha"

FEES_NOTE = (
    "The tradebook carries no charges, so they are estimated from the dated schedule for "
    "the venue (NSE or BSE equity delivery). A scrip's buys and sells on one day that offset "
    "each other are priced as intraday (inferred: the file has no product column)."
)

SUFFIX = {"NSE": ".NS", "BSE": ".BO"}
VENUE_SUFFIX = {"XNSE": ".NS", "XBOM": ".BO"}


class ImportNotAllowed(Exception):
    """409: the book can't take an import (not imported, archived, not INR)."""


class ImportInvalid(Exception):
    """422: the file or the request is unusable. The message names no value."""


class ImportMismatch(Exception):
    """409: the commit's file is not the previewed one."""


class ImportThrottled(Exception):
    """429: too many commits in the last hour."""


class ImportNotFound(Exception):
    """404: no such batch or opening lot in this book."""


# --- the book -------------------------------------------------------------------


def import_book(session: Session, user_id: int, book_id: int, *, write: bool) -> Portfolio:
    """The caller's imported book (404 for another user's, via ``resolve_book``)."""
    book = resolve_book(session, user_id, book_id)
    if book.kind != BookKind.IMPORTED:
        raise ImportNotAllowed(
            f"Book {book.name!r} is a paper book: trades are imported into an imported book."
        )
    if write and book.archived_at is not None:
        raise ImportNotAllowed(f"Book {book.name!r} is archived: unarchive it to import into it.")
    if write and (book.base_currency or "USD") != "INR":
        raise ImportNotAllowed(
            f"Book {book.name!r} is in {book.base_currency}: a Zerodha tradebook is in rupees, "
            "so import it into an INR book."
        )
    return book


def naive_utc(now: datetime) -> datetime:
    return now.astimezone(UTC).replace(tzinfo=None) if now.tzinfo is not None else now


def _venue_date(executed_at: datetime) -> date:
    return (executed_at + timedelta(hours=5, minutes=30)).date()


# --- instruments ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Listing:
    instrument_id: int
    ticker: str


def match_instruments(session: Session, rows: list[ParsedRow]) -> dict[int, Listing | None]:
    """Row number -> listing. ISIN first (``instrument_identifiers`` scheme
    ``isin``, the listing on the row's venue preferred), then symbol plus
    exchange (NSE -> ``.NS``, BSE -> ``.BO``). Users can't create instruments:
    an unmatched row is listed and skipped."""
    isins = {r.isin for r in rows if r.isin}
    by_isin: dict[str, list[tuple[int, str | None]]] = defaultdict(list)
    if isins:
        for ident, inst in session.exec(
            select(InstrumentIdentifier, Instrument)
            .join(Instrument, col(Instrument.id) == col(InstrumentIdentifier.instrument_id))
            .where(
                col(InstrumentIdentifier.scheme) == SCHEME_ISIN,
                col(InstrumentIdentifier.value).in_(sorted(isins)),
                col(InstrumentIdentifier.valid_to).is_(None),
            )
        ).all():
            by_isin[ident.value].append((ident.instrument_id, inst.mic))
    wanted = {f"{r.symbol}{SUFFIX[r.exchange]}" for r in rows}
    ticker_of: dict[int, str] = {}
    instrument_of_ticker: dict[str, int] = {}
    ids = {iid for hits in by_isin.values() for iid, _m in hits}
    for ident in session.exec(
        select(InstrumentIdentifier).where(
            col(InstrumentIdentifier.scheme) == SCHEME_YAHOO,
            col(InstrumentIdentifier.valid_to).is_(None),
            (col(InstrumentIdentifier.value).in_(sorted(wanted)))
            | (col(InstrumentIdentifier.instrument_id).in_(sorted(ids))),
        )
    ).all():
        ticker_of.setdefault(ident.instrument_id, ident.value)
        instrument_of_ticker.setdefault(ident.value, ident.instrument_id)
    known = set(
        session.exec(
            select(Symbol.ticker).where(
                col(Symbol.ticker).in_(sorted(set(ticker_of.values()) | wanted))
            )
        ).all()
    )
    out: dict[int, Listing | None] = {}
    for r in rows:
        listing: Listing | None = None
        hits = by_isin.get(r.isin or "", [])
        if hits:
            same = [iid for iid, mic in hits if mic == r.venue]
            iid = same[0] if same else None
            if iid is None:
                # The ISIN is recorded on another venue's listing: use this
                # venue's by symbol when it exists, else that listing.
                fallback = instrument_of_ticker.get(f"{r.symbol}{SUFFIX[r.exchange]}")
                iid = fallback if fallback is not None else hits[0][0]
            ticker = ticker_of.get(iid)
            if ticker is not None and ticker in known:
                listing = Listing(iid, ticker)
        if listing is None:
            ticker = f"{r.symbol}{SUFFIX[r.exchange]}"
            iid = instrument_of_ticker.get(ticker)
            if iid is not None and ticker in known:
                listing = Listing(iid, ticker)
        out[r.row] = listing
    return out


# --- ledger inputs ------------------------------------------------------------------


def due_splits(session: Session, instrument_ids: set[int], now: datetime) -> Splits:
    """Recorded splits whose ex-date session is complete on the venue (the
    rule ``corporate_actions.apply`` rebases paper books by)."""
    from stockviz.services.markets.calendar import latest_completed_session, venue_for_ticker

    if not instrument_ids:
        return {}
    aware = now if now.tzinfo is not None else now.replace(tzinfo=UTC)
    out: Splits = defaultdict(list)
    for action in session.exec(
        select(CorporateAction)
        .where(
            col(CorporateAction.kind) == "split",
            col(CorporateAction.instrument_id).in_(sorted(instrument_ids)),
        )
        .order_by(col(CorporateAction.ex_date))
    ).all():
        if action.instrument_id is None:
            continue
        if action.ex_date <= latest_completed_session(aware, venue_for_ticker(action.ticker)):
            out[action.instrument_id].append((action.ex_date, action.ratio))
    return dict(out)


def day_ranges(session: Session, fills: list[LedgerFill]) -> DayRanges:
    """The stored daily bar (low, high) of each fill's day, for the basis check."""
    wanted = {(f.instrument_id, f.venue_date) for f in fills if f.kind == FILL_TRADE}
    if not wanted:
        return {}
    ids = sorted({iid for iid, _d in wanted})
    first = min(d for _i, d in wanted)
    last = max(d for _i, d in wanted)
    out: DayRanges = {}
    for bar in session.exec(
        select(PriceBar).where(
            col(PriceBar.instrument_id).in_(ids),
            col(PriceBar.interval) == "1d",
            col(PriceBar.ts) >= datetime.combine(first, datetime.min.time()),
            col(PriceBar.ts) < datetime.combine(last + timedelta(days=1), datetime.min.time()),
        )
    ).all():
        key = (bar.instrument_id or 0, bar.ts.date())
        if key in wanted:
            out[key] = (bar.low, bar.high)
    return out


def ledger_fill(f: BrokerFill, *, key: int | None = None, seq: int = 0) -> LedgerFill:
    return LedgerFill(
        key=key if key is not None else (f.id or 0),
        instrument_id=f.instrument_id,
        ticker=f.ticker,
        venue=EQUITY_EXCHANGES.get(f.exchange, "XNSE"),
        kind=f.kind,
        side=f.side,
        quantity=f.quantity,
        price=f.price,
        executed_at=f.executed_at,
        venue_date=_venue_date(f.executed_at),
        seq=seq,
    )


def book_fills(session: Session, book_id: int) -> list[BrokerFill]:
    return list(
        session.exec(
            select(BrokerFill)
            .where(col(BrokerFill.portfolio_id) == book_id)
            .order_by(col(BrokerFill.executed_at), col(BrokerFill.id))
        ).all()
    )


def run_ledger(
    session: Session, fills: list[LedgerFill], now: datetime
) -> tuple[LedgerResult, Splits]:
    splits = due_splits(session, {f.instrument_id for f in fills}, now)
    return replay_fills(fills, splits=splits, day_ranges=day_ranges(session, fills)), splits


# --- preview -------------------------------------------------------------------------


@dataclass(slots=True)
class Problem:
    row: int
    kind: str
    reason: str
    field: str | None = None
    symbol: str | None = None
    exchange: str | None = None


@dataclass(slots=True)
class Analysis:
    parsed: ParsedFile
    new: list[tuple[ParsedRow, Listing]] = field(default_factory=list)
    problems: list[Problem] = field(default_factory=list)
    outcomes: dict[int, FillOutcome] = field(default_factory=dict)
    duplicate: int = 0
    unmatched: int = 0
    skipped_segment: int = 0
    rejected: int = 0


def analyse(session: Session, book: Portfolio, body: bytes, *, now: datetime) -> Analysis:
    """Parse, match, dedupe and run the ledger. Writes nothing."""
    assert book.id is not None
    try:
        parsed = parse_tradebook(body, today=_venue_date(naive_utc(now)))
    except FileRejected as exc:
        raise ImportInvalid(str(exc)) from exc
    result = Analysis(parsed=parsed)
    for p in parsed.problems:
        result.problems.append(Problem(p.row, p.kind, p.reason, p.field))
        if p.kind == KIND_SEGMENT:
            result.skipped_segment += 1
        else:
            result.rejected += 1
    if parsed.header.missing_required:
        return result

    listings = match_instruments(session, parsed.rows)
    in_file: dict[tuple[str, str], int] = defaultdict(int)
    for r in parsed.rows:
        in_file[(r.exchange, r.trade_id)] += 1
    keys = {(r.exchange, r.trade_id) for r in parsed.rows}
    existing: set[tuple[str, str]] = set()
    if keys:
        for exchange, trade_id in session.exec(
            select(BrokerFill.exchange, BrokerFill.trade_id).where(
                col(BrokerFill.portfolio_id) == book.id,
                col(BrokerFill.broker) == BROKER,
                col(BrokerFill.trade_id).in_(sorted({t for _e, t in keys})),
            )
        ).all():
            if trade_id is not None:
                existing.add((exchange, trade_id))

    for r in parsed.rows:
        key = (r.exchange, r.trade_id)
        if key in existing:
            result.duplicate += 1
            result.problems.append(
                Problem(r.row, "already_imported", "this trade id is already in the book")
            )
            continue
        if in_file[key] > 1:
            result.duplicate += 1
            result.problems.append(
                Problem(
                    r.row,
                    "duplicate_in_file",
                    "another row in this file has the same trade id: neither is imported",
                    "trade_id",
                )
            )
            continue
        listing = listings.get(r.row)
        if listing is None:
            result.unmatched += 1
            result.problems.append(
                Problem(
                    r.row,
                    "unmatched",
                    "no StockViz instrument has this ISIN or symbol on this exchange",
                    "symbol",
                    symbol=r.symbol,
                    exchange=r.exchange,
                )
            )
            continue
        result.new.append((r, listing))

    current = [ledger_fill(f) for f in book_fills(session, book.id)]
    # New fills get negative keys so they never collide with stored ids.
    pending = [
        LedgerFill(
            key=-(i + 1),
            instrument_id=listing.instrument_id,
            ticker=listing.ticker,
            venue=r.venue,
            kind=FILL_TRADE,
            side=r.side,
            quantity=r.quantity,
            price=r.price,
            executed_at=r.executed_at,
            venue_date=r.trade_date,
            seq=r.row,
        )
        for i, (r, listing) in enumerate(result.new)
    ]
    ledger, _splits = run_ledger(session, current + pending, now)
    for i, (r, listing) in enumerate(result.new):
        outcome = ledger.outcomes[-(i + 1)]
        result.outcomes[r.row] = outcome
        if outcome.status == STATUS_NEEDS_OPENING_LOT:
            result.problems.append(
                Problem(
                    r.row,
                    "needs_opening_lot",
                    "a sell with fewer shares held before it in this book: add an opening "
                    "lot for the shares bought before the file's window",
                    symbol=listing.ticker,
                )
            )
        if outcome.basis_uncertain:
            result.problems.append(
                Problem(
                    r.row,
                    "basis_uncertain",
                    "the price is far from the stored bar of that day after splits: a bonus, "
                    "rights issue or split is probably not recorded yet",
                    symbol=listing.ticker,
                )
            )
    result.problems.sort(key=lambda p: (p.row, p.kind))
    return result


def counts_of(a: Analysis) -> dict[str, int]:
    outcomes = list(a.outcomes.values())
    return {
        "rows": a.parsed.rows_total,
        "new": len(a.new),
        "posted": sum(1 for o in outcomes if o.posted),
        "needs_opening_lot": sum(1 for o in outcomes if o.status == STATUS_NEEDS_OPENING_LOT),
        "duplicate": a.duplicate,
        "unmatched": a.unmatched,
        "skipped_segment": a.skipped_segment,
        "rejected": a.rejected,
        "basis_uncertain": sum(1 for o in outcomes if o.basis_uncertain),
        "intraday_inferred": sum(1 for o in outcomes if o.intraday_quantity > 0),
        "intraday_short": sum(1 for o in outcomes if o.short == "open"),
    }


def preview(session: Session, user_id: int, book_id: int, body: bytes, *, now: datetime) -> dict:
    book = import_book(session, user_id, book_id, write=True)
    a = analyse(session, book, body, now=now)
    header = a.parsed.header
    message = None
    if header.missing_required:
        labels = [c.label for c in header.columns if c.field in header.missing_required]
        message = (
            "The file is missing required columns: " + ", ".join(labels) + ". "
            "If your tradebook names them differently, tell us the header row."
        )
    elif not a.new:
        message = "Nothing new to import." if a.parsed.rows_total else "The file has no rows."
    sample = []
    for r, listing in a.new[:SAMPLE_SIZE]:
        o = a.outcomes[r.row]
        sample.append(
            {
                "row": r.row,
                "ticker": listing.ticker,
                "symbol": r.symbol,
                "exchange": r.exchange,
                "isin": r.isin,
                "side": r.side,
                "quantity": r.quantity,
                "price": r.price,
                "executed_at": r.executed_at,
                "time_known": r.time_known,
                "restated_quantity": o.quantity,
                "restated_price": o.price,
                "product": o.product,
                "fees": o.fees,
                "status": o.status,
                "basis_uncertain": o.basis_uncertain,
                "intraday_short": o.short is not None,
            }
        )
    rollback(session)
    return {
        "format": columns.MAP_NAME,
        "format_status": columns.FORMAT_STATUS,
        "format_note": columns.FORMAT_NOTE,
        "file_sha256": a.parsed.sha256,
        "can_commit": not header.missing_required and bool(a.new),
        "message": message,
        "date_order": a.parsed.date_order,
        "columns": [
            {"field": c.field, "label": c.label, "required": c.required, "header": c.header}
            for c in header.columns
        ],
        "unmatched_headers": list(header.unmatched_headers),
        "missing_required": list(header.missing_required),
        "counts": counts_of(a),
        "sample": sample,
        "problems": [vars_of(p) for p in a.problems[:MAX_PROBLEMS]],
        "problems_total": len(a.problems),
        "fees_note": FEES_NOTE,
    }


def vars_of(p: Problem) -> dict:
    return {
        "row": p.row,
        "kind": p.kind,
        "reason": p.reason,
        "field": p.field,
        "symbol": p.symbol,
        "exchange": p.exchange,
    }


def rollback(session: Session) -> None:
    """Preview writes nothing; release anything the reads opened."""
    session.rollback()


# --- commit ---------------------------------------------------------------------------


def _throttle(session: Session, user_id: int, now: datetime) -> None:
    since = naive_utc(now) - timedelta(hours=1)
    recent = session.exec(
        select(func.count())
        .select_from(ImportBatch)
        .join(Portfolio, col(Portfolio.id) == col(ImportBatch.portfolio_id))
        .where(col(Portfolio.user_id) == user_id, col(ImportBatch.created_at) >= since)
    ).one()
    if recent >= MAX_COMMITS_PER_HOUR:
        raise ImportThrottled(f"At most {MAX_COMMITS_PER_HOUR} imports an hour. Try again later.")


def commit(
    session: Session,
    user_id: int,
    book_id: int,
    body: bytes,
    *,
    file_sha256: str,
    now: datetime,
) -> dict:
    book = import_book(session, user_id, book_id, write=True)
    assert book.id is not None
    a = analyse(session, book, body, now=now)
    if a.parsed.sha256 != file_sha256.strip().lower():
        session.rollback()
        raise ImportMismatch(
            "This is not the file you previewed. Preview it again before importing."
        )
    if a.parsed.header.missing_required:
        session.rollback()
        raise ImportInvalid("The file is missing required columns: preview it to see which.")
    counts = counts_of(a)
    if not a.new:
        session.rollback()
        return {"batch": None, "added": 0, "counts": counts}
    _throttle(session, user_id, now)
    book = lock_portfolio(session, book.id)
    batch = ImportBatch(
        portfolio_id=book.id or 0,
        broker=BROKER,
        column_map=columns.MAP_NAME,
        file_sha256=a.parsed.sha256,
        rows_total=a.parsed.rows_total,
        rows_added=len(a.new),
        rows_duplicate=a.duplicate,
        rows_unmatched=a.unmatched,
        rows_skipped_segment=a.skipped_segment,
        rows_rejected=a.rejected,
        created_at=naive_utc(now),
    )
    session.add(batch)
    session.flush()
    for r, listing in a.new:
        session.add(
            BrokerFill(
                portfolio_id=book.id or 0,
                import_batch_id=batch.id,
                kind=FILL_TRADE,
                broker=BROKER,
                exchange=r.exchange,
                segment=r.segment,
                series=r.series,
                trade_id=r.trade_id,
                order_id=r.order_id,
                instrument_id=listing.instrument_id,
                ticker=listing.ticker,
                isin=r.isin,
                raw_symbol=r.symbol,
                side=r.side,
                quantity=r.quantity,
                price=r.price,
                executed_at=r.executed_at,
                time_known=r.time_known,
                auction=r.auction,
                created_at=naive_utc(now),
            )
        )
    session.flush()
    rebuild_book(session, book, now=now)
    session.commit()
    session.refresh(batch)
    return {"batch": batch_out(session, batch), "added": len(a.new), "counts": counts}


# --- rebuild -----------------------------------------------------------------------------


@dataclass(slots=True)
class RebuildSummary:
    posted: int = 0
    waiting: int = 0
    holdings: int = 0


def rebuild_book(session: Session, book: Portfolio, *, now: datetime) -> RebuildSummary:
    """Replay every fill of the imported book into ``trades`` and ``positions``.
    Stages; the caller commits. Idempotent."""
    assert book.id is not None
    book_id = book.id
    fills = book_fills(session, book_id)
    ledger, _splits = run_ledger(session, [ledger_fill(f) for f in fills], now)
    trades = {
        t.broker_fill_id: t
        for t in session.exec(
            select(Trade).where(
                col(Trade.portfolio_id) == book_id, col(Trade.broker_fill_id).is_not(None)
            )
        ).all()
    }
    summary = RebuildSummary()
    posted: list[tuple[BrokerFill, FillOutcome, Trade]] = []
    removed: list[Trade] = []
    for f in fills:
        o = ledger.outcomes[f.id or 0]
        f.status = o.status
        if f.kind == FILL_TRADE:
            f.product = o.product
            f.fees = o.fees
            f.fee_source = FEE_ESTIMATED
            f.fee_lines = o.fee_lines
            f.basis_uncertain = o.basis_uncertain
        session.add(f)
        trade = trades.pop(f.id, None)
        if not o.posted:
            summary.waiting += 1
            if trade is not None:
                removed.append(trade)
            continue
        summary.posted += 1
        if trade is None:
            trade = Trade(
                portfolio_id=book_id,
                ticker=f.ticker,
                side=TradeSide(f.side),
                quantity=o.quantity,
                price=o.price,
                ts=f.executed_at,
                broker_fill_id=f.id,
            )
        trade.ticker = f.ticker
        trade.side = TradeSide(f.side)
        trade.quantity = o.quantity
        trade.price = o.price
        trade.ts = f.executed_at
        trade.fx_rate = Decimal(1)
        trade.realized_pnl = o.realized_pnl
        trade.avg_cost_at_fill = o.avg_cost_at_fill
        if f.kind == FILL_TRADE:
            trade.fees = o.fees
            trade.fee_schedule = o.fee_schedule or "none"
            trade.fee_lines = o.fee_lines
        else:
            trade.fees = None
            trade.fee_schedule = None
            trade.fee_lines = None
        session.add(trade)
        posted.append((f, o, trade))
    removed.extend(trades.values())  # trades whose fill is gone (a deleted batch)
    for trade in removed:
        session.delete(trade)
    session.exec(delete(Position).where(col(Position.portfolio_id) == book_id))  # type: ignore[call-overload]
    session.flush()
    for h in ledger.holdings:
        session.add(
            Position(
                portfolio_id=book_id,
                ticker=h.ticker,
                quantity=h.quantity,
                avg_cost=h.avg_cost,
            )
        )
        summary.holdings += 1
    session.flush()
    _pair_plans(session, book_id, posted)
    session.flush()
    return summary


def _pair_plans(
    session: Session, book_id: int, posted: list[tuple[BrokerFill, FillOutcome, Trade]]
) -> None:
    from stockviz.services.plans import record_fill

    plans = list(
        session.exec(
            select(TradePlan)
            .where(col(TradePlan.portfolio_id) == book_id)
            .order_by(col(TradePlan.created_at), col(TradePlan.id))
        ).all()
    )
    by_id = {p.id: p for p in plans}
    episode: dict[int, TradePlan | None] = {}
    ended: set[int] = set()
    used: set[int] = set()
    ordered = sorted(
        posted, key=lambda x: (x[2].ts, 0 if x[0].kind == FILL_OPENING else 1, x[0].id or 0)
    )
    for f, o, trade in ordered:
        iid = f.instrument_id
        if o.short is not None:
            # An intraday short and its cover pair no plan: imported plans are long only.
            continue
        if f.kind == FILL_OPENING:
            # An opening lot is the user's summary, not a fill: it pairs no
            # plan (link the position from the plans list instead).
            if o.held_before == 0:
                episode[iid] = None
            continue
        if trade.side == TradeSide.BUY:
            if o.held_before == 0:
                plan = by_id.get(trade.trade_plan_id) if trade.trade_plan_id else None
                if plan is None:
                    plan = next(
                        (
                            p
                            for p in reversed(plans)
                            if p.instrument_id == iid
                            and p.status == "open"
                            and p.first_fill_at is None
                            and p.id not in used
                            and p.created_at <= trade.ts
                        ),
                        None,
                    )
                episode[iid] = plan
            plan = episode.get(iid)
            if plan is not None and trade.trade_plan_id in (None, plan.id) and plan.id not in ended:
                trade.trade_plan_id = plan.id
                record_fill(plan, trade.ts)
                used.add(plan.id or 0)
                session.add(trade)
                session.add(plan)
        elif o.held_before - o.quantity == 0:
            plan = episode.pop(iid, None)
            if plan is not None and plan.id is not None:
                ended.add(plan.id)
    linked = set(
        session.exec(
            select(Trade.trade_plan_id).where(
                col(Trade.portfolio_id) == book_id, col(Trade.trade_plan_id).is_not(None)
            )
        ).all()
    )
    now = utcnow()
    for plan in plans:
        if plan.status != "active":
            continue
        if plan.id in ended or plan.id not in linked:
            plan.status = "closed"
            plan.updated_at = now
            session.add(plan)


# --- batches, opening lots ------------------------------------------------------------------


def batch_out(session: Session, batch: ImportBatch) -> dict:
    rows = session.exec(
        select(BrokerFill.status, BrokerFill.executed_at).where(
            col(BrokerFill.import_batch_id) == batch.id
        )
    ).all()
    times = [t for _s, t in rows]
    return {
        "id": batch.id,
        "created_at": batch.created_at,
        "column_map": batch.column_map,
        "format_status": columns.FORMAT_STATUS,
        "rows_total": batch.rows_total,
        "rows_added": batch.rows_added,
        "rows_duplicate": batch.rows_duplicate,
        "rows_unmatched": batch.rows_unmatched,
        "rows_skipped_segment": batch.rows_skipped_segment,
        "rows_rejected": batch.rows_rejected,
        "fills": len(rows),
        "posted": sum(1 for s, _t in rows if s == STATUS_POSTED),
        "needs_opening_lot": sum(1 for s, _t in rows if s == STATUS_NEEDS_OPENING_LOT),
        "first_trade_at": min(times) if times else None,
        "last_trade_at": max(times) if times else None,
    }


def imports_out(session: Session, user_id: int, book_id: int) -> dict:
    book = import_book(session, user_id, book_id, write=False)
    assert book.id is not None
    batches = session.exec(
        select(ImportBatch)
        .where(col(ImportBatch.portfolio_id) == book.id)
        .order_by(col(ImportBatch.created_at).desc(), col(ImportBatch.id).desc())
    ).all()
    fills = book_fills(session, book.id)
    lots = [f for f in fills if f.kind == FILL_OPENING]
    waiting: dict[str, list[BrokerFill]] = defaultdict(list)
    for f in fills:
        if f.status == STATUS_NEEDS_OPENING_LOT:
            waiting[f.ticker].append(f)
    needs = []
    if waiting:
        ledger, _s = run_ledger(session, [ledger_fill(f) for f in fills], utcnow())
        for ticker, rows in sorted(waiting.items()):
            first = rows[0]
            o = ledger.outcomes[first.id or 0]
            needs.append(
                {
                    "ticker": ticker,
                    "fills": len(rows),
                    "first_sell_at": first.executed_at,
                    "short_by": o.quantity - o.held_before,
                }
            )
    return {
        "book_id": book.id,
        "broker": book.broker,
        "format": columns.MAP_NAME,
        "format_status": columns.FORMAT_STATUS,
        "format_note": columns.FORMAT_NOTE,
        "max_bytes": MAX_FILE_BYTES,
        "batches": [batch_out(session, b) for b in batches],
        "opening_lots": [
            {
                "id": f.id,
                "ticker": f.ticker,
                "on": _venue_date(f.executed_at),
                "quantity": f.quantity,
                "avg_price": f.price,
                "created_at": f.created_at,
            }
            for f in lots
        ],
        "needs_opening_lot": needs,
        "basis_uncertain": sum(1 for f in fills if f.basis_uncertain),
        "fills": sum(1 for f in fills if f.kind == FILL_TRADE),
        "posted": sum(1 for f in fills if f.kind == FILL_TRADE and f.status == STATUS_POSTED),
    }


def delete_batch(
    session: Session, user_id: int, book_id: int, batch_id: int, *, now: datetime
) -> None:
    """Remove the batch, its fills and their trades (and plan links), then rebuild."""
    book = import_book(session, user_id, book_id, write=False)
    assert book.id is not None
    book = lock_portfolio(session, book.id)
    batch = session.get(ImportBatch, batch_id)
    if batch is None or batch.portfolio_id != book.id:
        session.rollback()
        raise ImportNotFound(f"Import {batch_id} not found")
    fill_ids = select(BrokerFill.id).where(col(BrokerFill.import_batch_id) == batch.id)
    for trade in session.exec(select(Trade).where(col(Trade.broker_fill_id).in_(fill_ids))).all():
        session.delete(trade)
    session.flush()
    session.exec(delete(BrokerFill).where(col(BrokerFill.import_batch_id) == batch.id))  # type: ignore[call-overload]
    session.delete(batch)
    session.flush()
    rebuild_book(session, book, now=now)
    session.commit()


def add_opening_lot(
    session: Session,
    user_id: int,
    book_id: int,
    *,
    ticker: str,
    on: date,
    quantity: Decimal,
    avg_price: Decimal,
    now: datetime,
) -> BrokerFill:
    """An opening lot: shares held before the file's window, at their average
    price, dated at the start of ``on`` (IST) so it comes before that day's
    trades. It has no fees and no trade id."""
    from stockviz.services.instruments import resolve_symbol

    book = import_book(session, user_id, book_id, write=True)
    assert book.id is not None
    ticker = ticker.strip().upper()
    venue_suffix = next((s for s in VENUE_SUFFIX.values() if ticker.endswith(s)), None)
    if venue_suffix is None:
        raise ImportInvalid("An opening lot is for an NSE (.NS) or BSE (.BO) symbol")
    if on > _venue_date(naive_utc(now)):
        raise ImportInvalid("An opening lot can't be dated in the future")
    instrument = resolve_symbol(session, ticker)
    if instrument is None or instrument.id is None or session.get(Symbol, ticker) is None:
        raise ImportNotFound(f"Unknown symbol {ticker}")
    count = session.exec(
        select(func.count())
        .select_from(BrokerFill)
        .where(col(BrokerFill.portfolio_id) == book.id, col(BrokerFill.kind) == FILL_OPENING)
    ).one()
    if count >= MAX_OPENING_LOTS_PER_BOOK:
        raise ImportNotAllowed(f"At most {MAX_OPENING_LOTS_PER_BOOK} opening lots a book")
    book = lock_portfolio(session, book.id)
    lot = BrokerFill(
        portfolio_id=book.id or 0,
        import_batch_id=None,
        kind=FILL_OPENING,
        broker=BROKER,
        exchange="NSE" if venue_suffix == ".NS" else "BSE",
        instrument_id=instrument.id,
        ticker=ticker,
        side="buy",
        quantity=quantity,
        price=avg_price,
        executed_at=ist_day_start(on),
        time_known=False,
        product=PRODUCT_DELIVERY,
        created_at=naive_utc(now),
    )
    session.add(lot)
    session.flush()
    rebuild_book(session, book, now=now)
    session.commit()
    session.refresh(lot)
    return lot


def delete_opening_lot(
    session: Session, user_id: int, book_id: int, lot_id: int, *, now: datetime
) -> None:
    book = import_book(session, user_id, book_id, write=False)
    assert book.id is not None
    book = lock_portfolio(session, book.id)
    lot = session.get(BrokerFill, lot_id)
    if lot is None or lot.portfolio_id != book.id or lot.kind != FILL_OPENING:
        session.rollback()
        raise ImportNotFound(f"Opening lot {lot_id} not found")
    for trade in session.exec(select(Trade).where(col(Trade.broker_fill_id) == lot.id)).all():
        session.delete(trade)
    session.flush()
    session.delete(lot)
    session.flush()
    rebuild_book(session, book, now=now)
    session.commit()
