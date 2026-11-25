"""Many watchlists per user, item notes and tags, column sets (A2.5, M4.6).

Rules:

- **Default list.** Every user has exactly one ``is_default`` list (partial
  unique index). ``ensure_default`` makes one on first use: it promotes the
  first list by position if none is flagged, else creates an empty
  "Default". Deleting the default list moves the flag to the first remaining
  list; deleting the last list leaves a fresh empty "Default", so a user
  always has a list and the old ``/v1/watchlist`` routes always have a target.
- **Names** are 1-64 characters after trimming and unique per user, ignoring
  case (409). At most ``MAX_LISTS`` lists a user.
- **Items.** At most ``MAX_ITEMS`` a list (the news filter's bound,
  ``routers/news.MAX_TICKERS``). A bulk add takes up to ``MAX_BULK`` tickers,
  de-duplicates them, skips those already listed and reports unknown ones;
  if the new total would pass ``MAX_ITEMS`` nothing is added (409).
- **Notes and tags.** A note is at most 2,000 characters (blank clears it). Up
  to 10 tags, each 1-24 characters (letters, digits, space, ``- _ . & /``),
  whitespace collapsed, de-duplicated ignoring case, order kept.
- **Column sets.** An ordered list of keys from ``COLUMN_KEYS`` (at least one, no
  repeats), named per user (unique ignoring case, at most ``MAX_COLUMN_SETS``).
  A list can remember one (``column_set_id``); deleting the set clears it.
- **Values.** ``column_values`` reads every requested key for every row in a
  fixed number of queries (no per-row reads; RS-12). A value with no data is
  ``None``, never 0.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import and_, func
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from stockviz._time import utcnow
from stockviz.models import PriceBar, Symbol, SymbolMetrics, Watchlist, WatchlistItem
from stockviz.models.checklist import ChecklistScore
from stockviz.models.eod import EodExtras
from stockviz.models.watchlist import (
    DEFAULT_WATCHLIST_NAME,
    NOTE_MAX,
    TAG_MAX_LENGTH,
    TAGS_MAX,
    WATCHLIST_COLOURS,
    ColumnSet,
)
from stockviz.services.instruments import instrument_ids, instrument_of
from stockviz.services.recent_bars import recent_bars

MAX_LISTS = 50
MAX_ITEMS = 100
MAX_BULK = 100
MAX_COLUMN_SETS = 20
MAX_COLUMNS = 19  # every key once (len(COLUMN_KEYS))
NAME_MAX = 64
SPARKLINE_BARS = 30

COLUMN_KEYS = (
    "close",
    "change_pct",
    "rsi_14",
    "pct_from_52w_high",
    "sma_50_gap_pct",
    "sma_200_gap_pct",
    "atr_pct_14",
    "hv_20",
    "volume_ratio",
    "avg_volume_20",
    "pe",
    "pb",
    "market_cap_usd",
    "dividend_yield",
    "roe",
    "sentiment_7d",
    "delivery_pct",
    "checklist_met",
    "sector",
)
"""The column allow-list. ``change_pct`` is the last close against the one
before; the ``*_gap_pct`` and ``pct_from_52w_high`` keys are percent gaps of
the snapshot's close to that level; ``volume_ratio`` is the latest session's
volume over the 20-day average; ``checklist_met`` is the latest Checklist
row's met count (``checklist_evaluated`` rides along)."""

DEFAULT_COLUMNS = ("close", "change_pct", "rsi_14", "pct_from_52w_high", "sector")

_METRIC_KEYS = {
    "rsi_14",
    "pct_from_52w_high",
    "sma_50_gap_pct",
    "sma_200_gap_pct",
    "atr_pct_14",
    "hv_20",
    "volume_ratio",
    "avg_volume_20",
    "pe",
    "pb",
    "market_cap_usd",
    "dividend_yield",
    "roe",
    "sentiment_7d",
}
_TAG_RE = re.compile(r"^[\w .&/-]+$")


def _http(code: int, detail: str) -> HTTPException:
    return HTTPException(code, detail)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def clean_name(raw: str) -> str:
    name = " ".join(raw.split())
    if not name or len(name) > NAME_MAX:
        raise _http(422, f"A name is 1 to {NAME_MAX} characters")
    return name


def clean_colour(raw: str) -> str:
    if raw not in WATCHLIST_COLOURS:
        raise _http(422, f"Colour must be one of {', '.join(WATCHLIST_COLOURS)}")
    return raw


def clean_note(raw: str | None) -> str | None:
    if raw is None:
        return None
    note = raw.strip()
    if len(note) > NOTE_MAX:
        raise _http(422, f"A note is at most {NOTE_MAX} characters")
    return note or None


def clean_tags(raw: Iterable[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in raw:
        tag = " ".join(str(value).split())
        if not tag:
            continue
        if len(tag) > TAG_MAX_LENGTH or not _TAG_RE.match(tag):
            raise _http(
                422,
                f"A tag is 1 to {TAG_MAX_LENGTH} letters, digits, spaces or - _ . & /",
            )
        if tag.casefold() in seen:
            continue
        seen.add(tag.casefold())
        out.append(tag)
    if len(out) > TAGS_MAX:
        raise _http(422, f"At most {TAGS_MAX} tags")
    return out


def clean_columns(raw: Sequence[str]) -> list[str]:
    columns = list(raw)
    if not columns or len(columns) > MAX_COLUMNS:
        raise _http(422, f"A column set has 1 to {MAX_COLUMNS} columns")
    unknown = [c for c in columns if c not in COLUMN_KEYS]
    if unknown:
        raise _http(422, f"Unknown column: {', '.join(unknown)}")
    if len(set(columns)) != len(columns):
        raise _http(422, "A column appears twice")
    return columns


# ---------------------------------------------------------------------------
# Lists
# ---------------------------------------------------------------------------


def lists_of(session: Session, user_id: int) -> list[Watchlist]:
    return list(
        session.exec(
            select(Watchlist)
            .where(Watchlist.user_id == user_id)
            .order_by(col(Watchlist.position), col(Watchlist.id))
        )
    )


def ensure_default(session: Session, user_id: int) -> Watchlist:
    """The user's default list, made or promoted on first use."""
    for _attempt in range(2):
        lists = lists_of(session, user_id)
        for wl in lists:
            if wl.is_default:
                return wl
        try:
            if lists:
                lists[0].is_default = True
                session.add(lists[0])
                session.commit()
                session.refresh(lists[0])
                return lists[0]
            wl = Watchlist(
                user_id=user_id, name=DEFAULT_WATCHLIST_NAME, is_default=True, position=0
            )
            session.add(wl)
            session.commit()
            session.refresh(wl)
            return wl
        except IntegrityError:
            # A concurrent request made it first; read theirs.
            session.rollback()
    raise _http(status.HTTP_409_CONFLICT, "Could not create the default watchlist")


def get_list(session: Session, user_id: int, watchlist_id: int) -> Watchlist:
    wl = session.get(Watchlist, watchlist_id)
    if wl is None or wl.user_id != user_id:
        raise _http(status.HTTP_404_NOT_FOUND, "Watchlist not found")
    return wl


def _name_taken(session: Session, user_id: int, name: str, *, except_id: int | None) -> bool:
    for wl in lists_of(session, user_id):
        if wl.id != except_id and wl.name.casefold() == name.casefold():
            return True
    return False


def create_list(session: Session, user_id: int, name: str, colour: str = "aqua") -> Watchlist:
    ensure_default(session, user_id)
    name, colour = clean_name(name), clean_colour(colour)
    lists = lists_of(session, user_id)
    if len(lists) >= MAX_LISTS:
        raise _http(status.HTTP_409_CONFLICT, f"At most {MAX_LISTS} watchlists")
    if _name_taken(session, user_id, name, except_id=None):
        raise _http(status.HTTP_409_CONFLICT, f"You already have a list named {name!r}")
    wl = Watchlist(
        user_id=user_id,
        name=name,
        colour=colour,
        position=max((w.position for w in lists), default=-1) + 1,
    )
    session.add(wl)
    try:
        session.commit()
    except IntegrityError as err:
        session.rollback()
        raise _http(status.HTTP_409_CONFLICT, f"You already have a list named {name!r}") from err
    session.refresh(wl)
    return wl


def update_list(
    session: Session,
    user_id: int,
    watchlist_id: int,
    *,
    fields: dict[str, Any],
) -> Watchlist:
    """Apply the fields that were sent: name, colour, is_default (true only),
    column_set_id (null clears)."""
    wl = get_list(session, user_id, watchlist_id)
    if "name" in fields and fields["name"] is not None:
        name = clean_name(fields["name"])
        if _name_taken(session, user_id, name, except_id=wl.id):
            raise _http(status.HTTP_409_CONFLICT, f"You already have a list named {name!r}")
        wl.name = name
    if "colour" in fields and fields["colour"] is not None:
        wl.colour = clean_colour(fields["colour"])
    if "column_set_id" in fields:
        set_id = fields["column_set_id"]
        if set_id is not None:
            get_column_set(session, user_id, set_id)
        wl.column_set_id = set_id
    if fields.get("is_default") is False:
        raise _http(422, "Make another list the default instead")
    if fields.get("is_default") and not wl.is_default:
        for other in lists_of(session, user_id):
            if other.is_default:
                other.is_default = False
                session.add(other)
        session.flush()  # the partial unique index allows one default
        wl.is_default = True
    session.add(wl)
    try:
        session.commit()
    except IntegrityError as err:
        session.rollback()
        raise _http(status.HTTP_409_CONFLICT, "That name is taken") from err
    session.refresh(wl)
    return wl


def reorder_lists(session: Session, user_id: int, ids: list[int]) -> list[Watchlist]:
    lists = lists_of(session, user_id)
    if sorted(ids) != sorted(w.id for w in lists if w.id is not None):
        raise _http(422, "Send every one of your list ids once, in the new order")
    by_id = {w.id: w for w in lists}
    for position, wid in enumerate(ids):
        by_id[wid].position = position
        session.add(by_id[wid])
    session.commit()
    return lists_of(session, user_id)


def delete_list(session: Session, user_id: int, watchlist_id: int) -> None:
    wl = get_list(session, user_id, watchlist_id)
    was_default = wl.is_default
    for item in session.exec(select(WatchlistItem).where(WatchlistItem.watchlist_id == wl.id)):
        session.delete(item)
    session.delete(wl)
    session.commit()
    if was_default:
        ensure_default(session, user_id)


def item_counts(session: Session, ids: list[int]) -> dict[int, int]:
    if not ids:
        return {}
    rows = session.exec(
        select(WatchlistItem.watchlist_id, func.count())
        .where(col(WatchlistItem.watchlist_id).in_(ids))
        .group_by(col(WatchlistItem.watchlist_id))
    ).all()
    return {wid: int(n) for wid, n in rows}


def lists_containing(session: Session, user_id: int, ticker: str) -> set[int]:
    rows = session.exec(
        select(WatchlistItem.watchlist_id)
        .join(Watchlist, col(Watchlist.id) == col(WatchlistItem.watchlist_id))
        .where(
            Watchlist.user_id == user_id,
            col(WatchlistItem.instrument_id) == instrument_of(ticker.upper()),
        )
    ).all()
    return set(rows)


# ---------------------------------------------------------------------------
# Items
# ---------------------------------------------------------------------------


def item_rows(session: Session, watchlist_id: int) -> list[tuple[WatchlistItem, Symbol]]:
    return list(
        session.exec(
            select(WatchlistItem, Symbol)
            .where(WatchlistItem.watchlist_id == watchlist_id)
            .join(Symbol, col(Symbol.ticker) == col(WatchlistItem.ticker))
            .order_by(col(WatchlistItem.added_at).desc(), col(WatchlistItem.ticker))
        )
    )


def find_item(session: Session, watchlist_id: int | None, ticker: str) -> WatchlistItem | None:
    """A list's row by public ticker (keyed by instrument since Phase 4.6b)."""
    return session.exec(
        select(WatchlistItem).where(
            col(WatchlistItem.watchlist_id) == watchlist_id,
            col(WatchlistItem.instrument_id) == instrument_of(ticker),
        )
    ).first()


@dataclass
class BulkResult:
    added: list[str]
    already_listed: list[str]
    unknown: list[str]
    item_count: int


def add_items(session: Session, wl: Watchlist, tickers: Sequence[str]) -> BulkResult:
    wanted: list[str] = []
    for raw in tickers:
        t = raw.strip().upper()
        if t and t not in wanted:
            wanted.append(t)
    if not wanted:
        raise _http(422, "Send at least one ticker")
    if len(wanted) > MAX_BULK:
        raise _http(422, f"At most {MAX_BULK} tickers at a time")
    known = {
        s.ticker for s in session.exec(select(Symbol).where(col(Symbol.ticker).in_(wanted))).all()
    }
    unknown = [t for t in wanted if t not in known]
    listed = {item.ticker for item, _sym in item_rows(session, wl.id)}  # type: ignore[arg-type]
    already = [t for t in wanted if t in known and t in listed]
    new = [t for t in wanted if t in known and t not in listed]
    if len(listed) + len(new) > MAX_ITEMS:
        raise _http(
            status.HTTP_409_CONFLICT,
            f"A list holds at most {MAX_ITEMS} symbols; this would make {len(listed) + len(new)}",
        )
    now = utcnow()
    for t in new:
        session.add(WatchlistItem(watchlist_id=wl.id, ticker=t, added_at=now))  # type: ignore[arg-type]
    try:
        session.commit()
    except IntegrityError as err:
        session.rollback()
        raise _http(status.HTTP_409_CONFLICT, "The list changed; try again") from err
    return BulkResult(new, already, unknown, len(listed) + len(new))


def update_item(
    session: Session, wl: Watchlist, ticker: str, *, fields: dict[str, Any]
) -> tuple[WatchlistItem, Symbol]:
    ticker = ticker.upper()
    item = find_item(session, wl.id, ticker)
    if item is None:
        raise _http(status.HTTP_404_NOT_FOUND, f"{ticker!r} is not on this list")
    if "note" in fields:
        item.note = clean_note(fields["note"])
    if "tags" in fields and fields["tags"] is not None:
        item.tags = clean_tags(fields["tags"])
    session.add(item)
    session.commit()
    session.refresh(item)
    symbol = session.get(Symbol, item.ticker)
    assert symbol is not None
    return item, symbol


def remove_item(session: Session, wl: Watchlist, ticker: str) -> None:
    ticker = ticker.upper()
    item = find_item(session, wl.id, ticker)
    if item is None:
        raise _http(status.HTTP_404_NOT_FOUND, f"{ticker!r} is not on the watchlist")
    session.delete(item)
    session.commit()


# ---------------------------------------------------------------------------
# Column sets
# ---------------------------------------------------------------------------


def column_sets_of(session: Session, user_id: int) -> list[ColumnSet]:
    return list(
        session.exec(
            select(ColumnSet).where(ColumnSet.user_id == user_id).order_by(col(ColumnSet.id))
        )
    )


def get_column_set(session: Session, user_id: int, set_id: int) -> ColumnSet:
    row = session.get(ColumnSet, set_id)
    if row is None or row.user_id != user_id:
        raise _http(status.HTTP_404_NOT_FOUND, "Column set not found")
    return row


def _set_name_taken(session: Session, user_id: int, name: str, *, except_id: int | None) -> bool:
    return any(
        s.id != except_id and s.name.casefold() == name.casefold()
        for s in column_sets_of(session, user_id)
    )


def create_column_set(
    session: Session, user_id: int, name: str, columns: Sequence[str]
) -> ColumnSet:
    name, cleaned = clean_name(name), clean_columns(columns)
    if len(column_sets_of(session, user_id)) >= MAX_COLUMN_SETS:
        raise _http(status.HTTP_409_CONFLICT, f"At most {MAX_COLUMN_SETS} column sets")
    if _set_name_taken(session, user_id, name, except_id=None):
        raise _http(status.HTTP_409_CONFLICT, f"You already have a column set named {name!r}")
    row = ColumnSet(user_id=user_id, name=name, columns=cleaned)
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def update_column_set(
    session: Session, user_id: int, set_id: int, *, fields: dict[str, Any]
) -> ColumnSet:
    row = get_column_set(session, user_id, set_id)
    if fields.get("name") is not None:
        name = clean_name(fields["name"])
        if _set_name_taken(session, user_id, name, except_id=row.id):
            raise _http(status.HTTP_409_CONFLICT, f"You already have a column set named {name!r}")
        row.name = name
    if fields.get("columns") is not None:
        row.columns = clean_columns(fields["columns"])
    row.updated_at = utcnow()
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def delete_column_set(session: Session, user_id: int, set_id: int) -> None:
    row = get_column_set(session, user_id, set_id)
    # SQLite does not enforce ON DELETE SET NULL without the pragma; do it here.
    for wl in session.exec(select(Watchlist).where(Watchlist.column_set_id == row.id)):
        wl.column_set_id = None
        session.add(wl)
    session.flush()
    session.delete(row)
    session.commit()


def resolve_columns(
    session: Session,
    user_id: int,
    wl: Watchlist,
    *,
    column_set_id: int | None,
    columns: str | None,
) -> tuple[list[str], int | None]:
    """The columns a read shows: ``columns=`` first, then ``column_set_id=``,
    then the list's saved set, then ``DEFAULT_COLUMNS``."""
    if columns is not None:
        return clean_columns([c.strip() for c in columns.split(",") if c.strip()]), None
    set_id = column_set_id if column_set_id is not None else wl.column_set_id
    if set_id is not None:
        row = get_column_set(session, user_id, set_id)
        return [c for c in row.columns if c in COLUMN_KEYS], row.id
    return list(DEFAULT_COLUMNS), None


# ---------------------------------------------------------------------------
# Values, batched
# ---------------------------------------------------------------------------


def _gap(close: Decimal | None, level: float | Decimal | None) -> float | None:
    if close is None or level is None or float(level) == 0:
        return None
    return (float(close) / float(level) - 1) * 100


def _latest_per_instrument(session: Session, model: Any, date_col: Any, ids: list[int], *where):
    """Rows of ``model`` at each instrument's newest ``date_col`` (one query)."""
    newest = (
        select(model.instrument_id, func.max(date_col).label("newest"))
        .where(col(model.instrument_id).in_(ids), *where)
        .group_by(model.instrument_id)
        .subquery()
    )
    return session.exec(
        select(model)
        .join(
            newest,
            and_(model.instrument_id == newest.c.instrument_id, date_col == newest.c.newest),
        )
        .where(*where)
    ).all()


def column_values(
    session: Session,
    rows: list[tuple[WatchlistItem, Symbol]],
    keys: Sequence[str],
    bars: dict[str, list[tuple[datetime, Decimal]]],
) -> dict[str, dict[str, Any]]:
    """``{ticker: {key: value}}`` for every row, in at most four queries."""
    tickers = [item.ticker for item, _sym in rows]
    out: dict[str, dict[str, Any]] = {t: {} for t in tickers}
    if not tickers or not keys:
        return out
    wanted = set(keys)
    ids = instrument_ids(session, tickers)
    by_instrument = {iid: t for t, iid in ids.items()}
    id_list = list(by_instrument)

    metrics: dict[str, SymbolMetrics] = {}
    if wanted & _METRIC_KEYS and id_list:
        for m in session.exec(
            select(SymbolMetrics).where(col(SymbolMetrics.instrument_id).in_(id_list))
        ).all():
            metrics[m.ticker] = m

    volumes: dict[str, int] = {}
    if "volume_ratio" in wanted and id_list:
        for bar in _latest_per_instrument(
            session, PriceBar, PriceBar.ts, id_list, PriceBar.interval == "1d"
        ):
            ticker = by_instrument.get(bar.instrument_id)
            if ticker is not None:
                volumes[ticker] = bar.volume

    delivery: dict[str, Decimal | None] = {}
    if "delivery_pct" in wanted and id_list:
        for row in _latest_per_instrument(session, EodExtras, EodExtras.session_date, id_list):
            ticker = by_instrument.get(row.instrument_id)
            # EQ first when a session has several series.
            if ticker is not None and (ticker not in delivery or row.series == "EQ"):
                delivery[ticker] = row.delivery_pct

    checklist: dict[str, ChecklistScore] = {}
    if "checklist_met" in wanted and id_list:
        for row in _latest_per_instrument(
            session, ChecklistScore, ChecklistScore.session_date, id_list
        ):
            ticker = by_instrument.get(row.instrument_id)
            if ticker is not None:
                checklist[ticker] = row

    for item, symbol in rows:
        t = item.ticker
        closes = [c for _ts, c in bars.get(t, [])]
        m = metrics.get(t)
        values = out[t]
        for key in keys:
            if key == "close":
                values[key] = float(closes[-1]) if closes else None
            elif key == "change_pct":
                values[key] = _gap(closes[-1], closes[-2]) if len(closes) >= 2 else None
            elif key == "sector":
                values[key] = symbol.sector
            elif key == "delivery_pct":
                d = delivery.get(t)
                values[key] = float(d) if d is not None else None
            elif key == "checklist_met":
                score = checklist.get(t)
                values[key] = score.met_count if score else None
                values["checklist_evaluated"] = score.evaluated_count if score else None
            elif m is None:
                values[key] = None
            elif key == "pct_from_52w_high":
                values[key] = _gap(m.last_close, m.high_52w)
            elif key == "sma_50_gap_pct":
                values[key] = _gap(m.last_close, m.sma_50)
            elif key == "sma_200_gap_pct":
                values[key] = _gap(m.last_close, m.sma_200)
            elif key == "volume_ratio":
                v = volumes.get(t)
                values[key] = v / m.avg_volume_20 if v is not None and m.avg_volume_20 else None
            else:
                values[key] = getattr(m, key)
    return out


def sparkline_bars(
    session: Session, tickers: list[str]
) -> dict[str, list[tuple[datetime, Decimal]]]:
    return recent_bars(session, tickers, limit_per_ticker=SPARKLINE_BARS)
