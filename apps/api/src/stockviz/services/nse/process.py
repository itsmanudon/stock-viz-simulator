"""One NSE file from disk to the database (A1.1): what ``nse-load`` runs.

``process_file(session, path, apply=False)`` reads, hashes, parses, checks
the date and matches rows to instruments, and writes nothing (not even the
archive). With ``apply=True`` it archives the file, records it in
``data_files`` and, when it parsed and its date is right, loads it, all in
one transaction. A load that raises is rolled back and the file is recorded
as ``failed`` with the error.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from sqlmodel import Session

from stockviz.models.data_file import (
    PARSE_DATE_MISMATCH,
    PARSE_FAILED,
    PARSE_PARSED,
    PARSE_UNRECOGNISED,
)
from stockviz.services.nse.archive import (
    archive_copy,
    archive_root,
    record_file,
    recorded_file,
    sha256_hex,
)
from stockviz.services.nse.formats import (
    UNKNOWN_SOURCE,
    ParseError,
    UnrecognisedFile,
    date_from_file_name,
    read_bytes_as_text,
)
from stockviz.services.nse.load import LoadPlan, LoadResult, apply_load, plan_load
from stockviz.services.nse.parse import ParsedFile, check_date, parse_any


@dataclass
class FileReport:
    path: str
    status: str  # a data_files parse status, or "already recorded"
    source: str = UNKNOWN_SOURCE
    trading_date: date | None = None
    sha256: str | None = None
    error: str | None = None
    plan: LoadPlan | None = None
    result: LoadResult | None = None
    data_file_id: int | None = None
    archived_path: str | None = None

    @property
    def ok(self) -> bool:
        return self.status in (PARSE_PARSED, ALREADY_RECORDED)


ALREADY_RECORDED = "already recorded"


def _inspect(data: bytes, file_name: str) -> tuple[str, str, ParsedFile | None, str | None]:
    """(status, source, parsed, error) for a file's bytes."""
    try:
        parsed = parse_any(read_bytes_as_text(data))
    except UnrecognisedFile as exc:
        return PARSE_UNRECOGNISED, UNKNOWN_SOURCE, None, str(exc)
    except ParseError as exc:
        return PARSE_FAILED, UNKNOWN_SOURCE, None, str(exc)
    reason = check_date(parsed, date_from_file_name(file_name))
    if reason is not None:
        return PARSE_DATE_MISMATCH, parsed.format.value, parsed, reason
    return PARSE_PARSED, parsed.format.value, parsed, None


def process_file(
    session: Session, path: Path, *, apply: bool, root: Path | None = None
) -> FileReport:
    try:
        data = path.read_bytes()
    except OSError as exc:
        return FileReport(path=str(path), status=PARSE_FAILED, error=f"cannot read: {exc}")
    sha = sha256_hex(data)
    known = recorded_file(session, sha)
    if known is not None:
        return FileReport(
            path=str(path),
            status=ALREADY_RECORDED,
            source=known.source,
            trading_date=known.trading_date,
            sha256=sha,
            data_file_id=known.id,
            archived_path=known.archived_path,
        )

    status, source, parsed, error = _inspect(data, path.name)
    day = parsed.trading_date if parsed is not None else None
    report = FileReport(
        path=str(path), status=status, source=source, trading_date=day, sha256=sha, error=error
    )
    if status == PARSE_PARSED and parsed is not None:
        report.plan = plan_load(session, parsed)
    if not apply:
        return report

    target = archive_copy(
        data,
        root=root or archive_root(),
        source=source,
        trading_date=day or date_from_file_name(path.name),
        file_name=path.name,
    )
    report.archived_path = str(target)
    rows_total = len(parsed.rows) if parsed is not None else 0
    try:
        row = record_file(
            session,
            source=source,
            trading_date=day,
            file_name=path.name,
            sha256=sha,
            size_bytes=len(data),
            archived_path=target,
            parse_status=status,
            rows_total=rows_total,
            error=error,
        )
        assert row.id is not None
        if report.plan is not None:
            report.result = apply_load(session, report.plan, data_file_id=row.id, source=source)
            row.rows_loaded = report.result.loaded
            session.add(row)
        session.commit()
        report.data_file_id = row.id
    except Exception as exc:  # recorded as failed; the CLI exits 1
        session.rollback()
        report.status = PARSE_FAILED
        report.error = f"load failed: {exc}"[:2000]
        report.result = None
        failed = record_file(
            session,
            source=source,
            trading_date=day,
            file_name=path.name,
            sha256=sha,
            size_bytes=len(data),
            archived_path=target,
            parse_status=PARSE_FAILED,
            rows_total=rows_total,
            error=report.error,
        )
        session.commit()
        report.data_file_id = failed.id
    return report
