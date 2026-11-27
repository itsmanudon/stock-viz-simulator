"""Load the owner's NSE index option minute files as daily summaries (A7.14).

Format (header row, read by name): ``date,time,symbol,option_type,type,
strike_offset,open,high,low,close,volume,oi,iv,spot``; ``date`` is written as
an Excel formula string (``="10-06-24"``, day-month-year); ``time`` is IST;
``type`` CE/PE; ``strike_offset`` ATM, ATM+3, ATM-2. A row that does not read
is rejected and counted (line numbers listed, never values). Minutes outside
09:15-15:30 are left out of the summary.

The series is the folder: ``weekly`` for the NIFTY weekly files, else
``nearest`` (the files do not state expiries). Every file of a run is read
together, because a day can span two part files; the summaries are then
upserted, so a rerun writes the same rows. Local database only
(``intraday.guard``); dry run by default.
"""

from __future__ import annotations

import csv
import hashlib
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel import Session, select

from stockviz.models import FoDaily, FoFile
from stockviz.services.intraday.guard import local_database_problem

REQUIRED = (
    "date",
    "time",
    "symbol",
    "type",
    "strike_offset",
    "close",
    "volume",
    "oi",
    "iv",
    "spot",
)
OPEN, CLOSE = "09:15:00", "15:30:00"
CHUNK = 2000


class FoLoadRefused(RuntimeError):
    pass


@dataclass
class FileReport:
    path: str
    series: str
    rows: int = 0
    rejected: int = 0
    off_session: int = 0
    first_bad_lines: list[int] = field(default_factory=list)
    known: bool = False
    skipped: str | None = None


@dataclass
class _Agg:
    close: Decimal
    iv: float | None
    oi: int | None
    spot: Decimal
    last: str
    volume: int = 0
    minutes: int = 0


@dataclass
class LoadReport:
    files: list[FileReport]
    summaries: int
    applied: bool
    days: dict[tuple[str, str], tuple[date, date]]


def series_for(path: Path) -> str:
    return "weekly" if path.parent.name.lower() == "weekly" else "nearest"


def parse_day(raw: str) -> date:
    text = raw.strip().lstrip("=").strip('"')
    d, m, y = (int(p) for p in text.split("-"))
    return date(2000 + y if y < 100 else y, m, d)


def parse_offset(raw: str) -> int:
    text = raw.strip().upper()
    if text == "ATM":
        return 0
    if not text.startswith("ATM") or len(text) < 5 or text[3] not in "+-":
        raise ValueError("offset")
    return int(text[3:])


def _rows(path: Path) -> Iterator[tuple[int, dict[str, str]]]:
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        missing = [c for c in REQUIRED if c not in (reader.fieldnames or [])]
        if missing:
            raise FoLoadRefused(f"{path.name}: missing columns {', '.join(missing)}")
        yield from enumerate(reader, start=2)


def aggregate(
    paths: list[Path],
) -> tuple[dict[tuple[str, str, date, str, int], _Agg], list[FileReport]]:
    agg: dict[tuple[str, str, date, str, int], _Agg] = {}
    reports: list[FileReport] = []
    for path in paths:
        report = FileReport(str(path), series_for(path))
        reports.append(report)
        try:
            rows = list(_rows(path))
        except FoLoadRefused as exc:
            report.skipped = f"not an options file ({exc})"
            continue
        for line, row in rows:
            report.rows += 1
            try:
                day = parse_day(row["date"])
                minute = row["time"].strip()[:8]
                kind = row["type"].strip().upper()
                if kind not in ("CE", "PE"):
                    raise ValueError("type")
                key = (
                    row["symbol"].strip().upper(),
                    report.series,
                    day,
                    kind,
                    parse_offset(row["strike_offset"]),
                )
                close = Decimal(row["close"])
                spot = Decimal(row["spot"])
                iv = float(row["iv"]) if row["iv"].strip() else None
                oi = int(float(row["oi"])) if row["oi"].strip() else None
                volume = int(float(row["volume"] or 0))
            except (ValueError, KeyError, InvalidOperation, AttributeError):
                report.rejected += 1
                if len(report.first_bad_lines) < 5:
                    report.first_bad_lines.append(line)
                continue
            if not (OPEN <= minute <= CLOSE):
                report.off_session += 1
                continue
            cur = agg.get(key)
            if cur is None:
                agg[key] = _Agg(close, iv, oi, spot, minute, volume, 1)
                continue
            cur.volume += volume
            cur.minutes += 1
            if minute >= cur.last:
                cur.close, cur.iv, cur.oi, cur.spot, cur.last = close, iv, oi, spot, minute
    return agg, reports


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def load_dir(session: Session, directory: Path, *, apply: bool = False) -> LoadReport:
    problem = local_database_problem(session.get_bind().engine.url)
    if problem is not None:
        raise FoLoadRefused(
            f"refusing to load the owner's F&O files: {problem}. They load into a local "
            "database only (owner, 27 Nov 2026); there is no override."
        )
    paths = sorted(p for p in directory.rglob("*.csv") if p.is_file())
    if not paths:
        raise FoLoadRefused(f"no .csv files under {directory}")
    agg, reports = aggregate(paths)
    days: dict[tuple[str, str], tuple[date, date]] = {}
    for und, series, day, _k, _o in agg:
        lo, hi = days.get((und, series), (day, day))
        days[(und, series)] = (min(lo, day), max(hi, day))
    for report, path in zip(reports, paths, strict=True):
        report.known = (
            session.exec(select(FoFile).where(FoFile.sha256 == _sha(path))).first() is not None
        )
    if apply:
        rows = [
            {
                "underlying": und,
                "series": series,
                "day": day,
                "option_type": kind,
                "strike_offset": offset,
                "close": a.close,
                "iv": a.iv,
                "oi": a.oi,
                "volume": a.volume,
                "spot": a.spot,
                "last_minute": a.last,
                "minutes": a.minutes,
            }
            for (und, series, day, kind, offset), a in agg.items()
        ]
        insert = pg_insert if session.get_bind().dialect.name == "postgresql" else sqlite_insert
        keys = ["underlying", "series", "day", "option_type", "strike_offset"]
        for i in range(0, len(rows), CHUNK):
            stmt = insert(FoDaily).values(rows[i : i + CHUNK])
            stmt = stmt.on_conflict_do_update(
                index_elements=keys,
                set_={c: stmt.excluded[c] for c in rows[0] if c not in keys},
            )
            session.exec(stmt)  # type: ignore[arg-type]
        for report, path in zip(reports, paths, strict=True):
            if not report.known and report.skipped is None:
                session.add(
                    FoFile(
                        sha256=_sha(path),
                        file_name=path.name,
                        series=report.series,
                        size_bytes=path.stat().st_size,
                        rows_total=report.rows,
                        rows_rejected=report.rejected,
                    )
                )
        session.commit()
    return LoadReport(reports, len(agg), apply, days)
