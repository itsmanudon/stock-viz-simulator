"""``stockviz.cli intraday-load``: the owner's intraday files into ``intraday_bars`` (A6.1).

Local only, always: :func:`load_files` refuses any database that is not on
this machine (``guard.py``), in a dry run as well as with ``apply``, and no
argument turns that off.

Per file:

1. **Instrument.** The ticker comes from the file name (``files.py``). An
   unknown ticker is reported; with ``create_symbols`` and ``apply`` its
   ``symbols`` row is added (INR, NSE) and the identity rules make its
   instrument. An index's zero volume is stored as 0: the instrument is
   ``asset_type = 'index'``, which is the flag that its volume is not real.
2. **Rows.** Unreadable or impossible rows (bad time, bad number, low above
   open/close, a non-positive price, negative volume) are rejected and
   counted. A row whose time is repeated in the file is a duplicate (the
   first is kept).
3. **Session.** Each bar is checked against its venue's session hours
   (``calendar.session_minutes``, special sessions included): a 1-minute bar
   must open inside a trading span, a 60-minute bar must overlap one. Bars
   outside are counted per day and not loaded.
4. **Write** (``apply``). The file is recorded in ``intraday_files`` (SHA-256
   unique), the months it touches get their partitions, and the rows go
   through a temporary table filled by ``COPY`` into ``intraday_bars`` with
   ``ON CONFLICT DO NOTHING``: a rerun inserts nothing, and a row already
   stored is never changed. One transaction per file.

MoneyControl files are not loaded: ``reconcile.reconcile_moneycontrol``.
"""

from __future__ import annotations

import hashlib
import time as clock
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from sqlalchemy import insert, text
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel import Session, col, select

from stockviz._time import utcnow
from stockviz.models.instrument import Instrument
from stockviz.models.intraday import IntradayBar, IntradayFile
from stockviz.models.market import Symbol
from stockviz.services.instruments import instrument_ids
from stockviz.services.intraday.files import (
    IST_OFFSET,
    FileKind,
    FormatError,
    ParseProblems,
    Row,
    discover,
    file_stem,
    read_rows,
)
from stockviz.services.intraday.guard import require_local_database
from stockviz.services.intraday.partitions import ensure_month_partitions, month_of
from stockviz.services.markets.calendar import SessionHours, session_minutes, venue_for_ticker

FEED_FILE = "file"
SQLITE_CHUNK = 500


@dataclass
class FileReport:
    file_name: str
    ticker: str
    kind: str
    venue: str
    status: str = "planned"  # planned | loaded | unmatched | failed
    error: str | None = None
    instrument_id: int | None = None
    is_index: bool = False
    symbol_created: bool = False
    would_create_symbol: bool = False
    rows_total: int = 0
    invalid: int = 0
    duplicate: int = 0
    off_session: int = 0
    no_calendar: int = 0
    accepted: int = 0
    already_stored: int = 0
    inserted: int = 0
    nonzero_volume: int = 0
    first_ts: datetime | None = None
    last_ts: datetime | None = None
    sessions: int = 0
    off_session_days: Counter[date] = field(default_factory=Counter)
    problem_lines: list[int] = field(default_factory=list)
    seconds: float = 0.0

    @property
    def new(self) -> int:
        """Rows a load would add (accepted minus already stored)."""
        return self.accepted - self.already_stored


@dataclass
class Accepted:
    rows: list[Row]
    available_at: list[datetime]


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def indian_venue(ticker: str) -> str:
    """The venue the owner's (Indian) files are judged on: BSE for Sensex, else NSE."""
    if ticker.upper() == "^BSESN" or ticker.upper().endswith(".BO"):
        return "XBOM"
    venue = venue_for_ticker(ticker)
    return venue if venue in {"XNSE", "XBOM"} else "XNSE"


def classify(
    rows: Sequence[Row],
    kind: FileKind,
    venue: str,
    report: FileReport,
) -> Accepted:
    """Session-check and de-duplicate parsed rows; fill the report's counts."""
    hours_by_day: dict[date, SessionHours | None] = {}
    seen: set[datetime] = set()
    accepted: list[Row] = []
    available: list[datetime] = []
    days: set[date] = set()
    length = timedelta(minutes=kind.minutes)
    for row in rows:
        report.rows_total += 1
        if row.ts in seen:
            report.duplicate += 1
            continue
        seen.add(row.ts)
        day = (row.ts + IST_OFFSET).date()
        if day not in hours_by_day:
            hours_by_day[day] = session_minutes(day, venue)
        hours = hours_by_day[day]
        start = row.ts.replace(tzinfo=UTC)
        inside = hours is not None and (
            hours.contains(start) if kind.minutes == 1 else hours.overlaps(start, start + length)
        )
        if not inside:
            report.off_session += 1
            report.off_session_days[day] += 1
            continue
        assert hours is not None
        accepted.append(row)
        available.append(min(start + length, hours.close).replace(tzinfo=None))
        days.add(day)
        if row.volume:
            report.nonzero_volume += 1
    report.accepted = len(accepted)
    report.sessions = len(days)
    if accepted:
        report.first_ts = min(r.ts for r in accepted)
        report.last_ts = max(r.ts for r in accepted)
    return Accepted(accepted, available)


def _stored_ts(session: Session, instrument_id: int, kind: FileKind, lo: datetime, hi: datetime):
    stmt = select(IntradayBar.ts).where(
        col(IntradayBar.instrument_id) == instrument_id,
        col(IntradayBar.feed) == FEED_FILE,
        col(IntradayBar.interval) == kind.interval,
        col(IntradayBar.ts) >= lo,
        col(IntradayBar.ts) <= hi,
    )
    return set(session.exec(stmt).all())


def _record_file(session: Session, path: Path, sha: str, kind: FileKind, report: FileReport) -> int:
    record = session.exec(select(IntradayFile).where(col(IntradayFile.sha256) == sha)).first()
    if record is None:
        assert kind.file_kind is not None and report.instrument_id is not None
        record = IntradayFile(
            kind=kind.file_kind,
            file_name=path.name,
            sha256=sha,
            size_bytes=path.stat().st_size,
            instrument_id=report.instrument_id,
        )
    record.rows_total = report.rows_total
    record.rows_accepted = report.accepted
    record.rows_off_session = report.off_session
    record.rows_invalid = report.invalid
    record.rows_duplicate = report.duplicate
    record.first_ts = report.first_ts
    record.last_ts = report.last_ts
    record.loaded_at = utcnow()
    session.add(record)
    session.flush()
    assert record.id is not None
    return record.id


def _bar_tuples(accepted: Accepted, instrument_id: int, kind: FileKind, file_id: int):
    now = utcnow()
    for row, available_at in zip(accepted.rows, accepted.available_at, strict=True):
        yield (
            instrument_id,
            FEED_FILE,
            kind.interval,
            row.ts,
            row.open,
            row.high,
            row.low,
            row.close,
            row.volume,
            kind.source,
            file_id,
            now,
            available_at,
        )


_COLUMNS = (
    "instrument_id",
    "feed",
    "interval",
    "ts",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "source",
    "file_id",
    "ingested_at",
    "available_at",
)


def _write_postgres(session: Session, tuples) -> int:
    conn = session.connection()
    cols = ", ".join(_COLUMNS)
    conn.execute(
        text(
            "CREATE TEMP TABLE IF NOT EXISTS intraday_stage ("
            "instrument_id bigint, feed varchar(8), interval varchar(4), ts timestamp, "
            "open numeric(18,6), high numeric(18,6), low numeric(18,6), close numeric(18,6), "
            "volume bigint, source varchar(24), file_id integer, ingested_at timestamp, "
            "available_at timestamp) ON COMMIT DELETE ROWS"
        )
    )
    raw = conn.connection.driver_connection
    assert raw is not None
    with raw.cursor() as cur, cur.copy(f"COPY intraday_stage ({cols}) FROM STDIN") as copy:
        for item in tuples:
            copy.write_row(item)
    result = conn.execute(
        text(
            f"INSERT INTO intraday_bars ({cols}) SELECT {cols} FROM intraday_stage "
            "ON CONFLICT DO NOTHING"
        )
    )
    return int(result.rowcount or 0)


def _write_generic(session: Session, tuples) -> int:
    conn = session.connection()
    table = IntradayBar.__table__  # pyright: ignore[reportAttributeAccessIssue]
    inserted = 0
    batch: list[dict[str, object]] = []

    def flush() -> int:
        if not batch:
            return 0
        if conn.dialect.name == "sqlite":
            stmt = sqlite_insert(table).on_conflict_do_nothing()
        else:  # pragma: no cover - only SQLite and PostgreSQL are supported
            stmt = insert(table)
        result = conn.execute(stmt, batch)
        batch.clear()
        return int(result.rowcount or 0)

    for item in tuples:
        batch.append(dict(zip(_COLUMNS, item, strict=True)))
        if len(batch) >= SQLITE_CHUNK:
            inserted += flush()
    inserted += flush()
    return inserted


def _instrument(session: Session, ticker: str) -> tuple[int | None, bool]:
    found = instrument_ids(session, [ticker]).get(ticker)
    if found is None:
        return None, False
    asset_type = session.exec(
        select(Instrument.asset_type).where(col(Instrument.id) == found)
    ).first()
    return found, asset_type == "index"


def _create_symbol(session: Session, ticker: str, stem: str) -> None:
    bse = ticker.upper() == "^BSESN"
    session.add(
        Symbol(
            ticker=ticker,
            name=stem,
            currency="INR",
            exchange="BSE" if bse else "NSE",
            is_active=True,
        )
    )
    session.commit()


def load_file(
    session: Session,
    path: Path,
    ticker: str,
    kind: FileKind,
    *,
    apply: bool,
    create_symbols: bool = False,
) -> FileReport:
    """Plan (and with ``apply`` write) one file. The caller has checked the database is local."""
    started = clock.monotonic()
    venue = indian_venue(ticker)
    report = FileReport(file_name=path.name, ticker=ticker, kind=kind.key, venue=venue)
    stem = file_stem(kind, path.name) or ticker
    instrument_id, is_index = _instrument(session, ticker)
    if instrument_id is None and create_symbols:
        if apply:
            _create_symbol(session, ticker, stem)
            instrument_id, is_index = _instrument(session, ticker)
            report.symbol_created = instrument_id is not None
        else:
            report.would_create_symbol = True
    report.instrument_id = instrument_id
    report.is_index = is_index
    problems = ParseProblems()
    try:
        accepted = classify(list(read_rows(path, kind, problems)), kind, venue, report)
    except (FormatError, UnicodeDecodeError) as exc:
        report.status = "failed"
        report.error = str(exc) if isinstance(exc, FormatError) else "not UTF-8 text"
        report.seconds = clock.monotonic() - started
        return report
    report.invalid = problems.total
    report.rows_total += problems.total
    report.problem_lines = list(problems.first_lines or [])

    if instrument_id is None:
        report.status = "unmatched"
        report.seconds = clock.monotonic() - started
        return report
    if accepted.rows and report.first_ts is not None and report.last_ts is not None:
        stored = _stored_ts(session, instrument_id, kind, report.first_ts, report.last_ts)
        report.already_stored = sum(1 for r in accepted.rows if r.ts in stored)

    if apply and kind.stored:
        try:
            file_id = _record_file(session, path, sha256_of(path), kind, report)
            ensure_month_partitions(session.connection(), {month_of(r.ts) for r in accepted.rows})
            tuples = _bar_tuples(accepted, instrument_id, kind, file_id)
            postgres = session.connection().dialect.name == "postgresql"
            report.inserted = (_write_postgres if postgres else _write_generic)(session, tuples)
            record = session.get(IntradayFile, file_id)
            if record is not None:
                record.rows_inserted = report.inserted
                session.add(record)
            session.commit()
            report.status = "loaded"
        except Exception as exc:
            session.rollback()
            report.status = "failed"
            report.error = type(exc).__name__
    report.seconds = clock.monotonic() - started
    return report


def load_files(
    session: Session,
    files: Sequence[tuple[Path, str]],
    kind: FileKind,
    *,
    apply: bool,
    create_symbols: bool = False,
    progress: Callable[[int, int, FileReport], None] | None = None,
) -> list[FileReport]:
    """Every file in order; refuses a database that is not local before anything else."""
    bind = session.get_bind()
    require_local_database(bind.engine.url if hasattr(bind, "engine") else bind.url)  # pyright: ignore[reportAttributeAccessIssue]
    if not kind.stored and apply:
        raise ValueError(f"{kind.key} files are reconciliation only; nothing is written")
    reports: list[FileReport] = []
    for index, (path, ticker) in enumerate(files, start=1):
        report = load_file(session, path, ticker, kind, apply=apply, create_symbols=create_symbols)
        reports.append(report)
        if progress is not None:
            progress(index, len(files), report)
    return reports


def files_in(directory: Path, kind: FileKind, only: Sequence[str] | None = None):
    """The kind's files in ``directory`` (optionally only these tickers)."""
    found = discover(directory, kind)
    if only:
        wanted = {t.upper() for t in only}
        found = [(p, t) for p, t in found if t.upper() in wanted]
    return found
