"""Load hand-placed document files (A7.10): concall transcripts, filings,
announcements and annual reports the owner saved locally.

Dry run by default: each file's type, size, SHA-256, characters of text and
whether it is new; nothing is written. ``apply`` stores new ones. Like the
owner's intraday files, these load into a local database only
(``intraday.guard.local_database_problem``); there is no override.

``available_at`` is when the document became public. Pass it when known
(``--available-at``); otherwise ``--date`` is taken as the end of that day in
the listing venue's time zone and marked assumed, so it never leaks into
earlier sessions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time
from pathlib import Path

from sqlmodel import Session

from stockviz.models.document import DOCUMENT_KINDS
from stockviz.services.documents.extract import ExtractError, content_type_for, extract
from stockviz.services.documents.store import NewDocument, add_document, find_by_hash, sha256_of
from stockviz.services.instruments import instrument_ids
from stockviz.services.intraday.guard import local_database_problem
from stockviz.services.markets.calendar import venue_for_ticker, venue_zone


class LoadRefused(RuntimeError):
    """A run that cannot start (bad arguments or a remote database)."""


@dataclass
class FileResult:
    path: str
    status: str  # new | stored | duplicate | refused
    content_type: str | None = None
    size_bytes: int = 0
    text_chars: int = 0
    sha256: str | None = None
    reason: str | None = None
    document_id: int | None = None


@dataclass
class LoadReport:
    ticker: str
    kind: str
    available_at: datetime
    available_assumed: bool
    applied: bool
    files: list[FileResult] = field(default_factory=list)

    @property
    def refused(self) -> list[FileResult]:
        return [f for f in self.files if f.status == "refused"]


def resolve_available_at(
    ticker: str, *, on: date | None, available_at: datetime | None
) -> tuple[datetime, bool]:
    """(naive UTC instant, assumed?) for a document's release."""
    if available_at is not None:
        if available_at.tzinfo is not None:
            available_at = available_at.astimezone(UTC).replace(tzinfo=None)
        return available_at, False
    if on is None:
        raise LoadRefused("give --available-at (when it was public) or --date")
    zone = venue_zone(venue_for_ticker(ticker))
    end = datetime.combine(on, time(23, 59), tzinfo=zone)
    return end.astimezone(UTC).replace(tzinfo=None), True


def load_files(
    session: Session,
    paths: list[Path],
    *,
    ticker: str,
    kind: str,
    on: date | None = None,
    available_at: datetime | None = None,
    title: str | None = None,
    form_type: str | None = None,
    apply: bool = False,
) -> LoadReport:
    problem = local_database_problem(session.get_bind().engine.url)
    if problem is not None:
        raise LoadRefused(
            f"refusing to load document files: {problem}. Hand-placed files load into a "
            "local database only; there is no override."
        )
    if kind not in DOCUMENT_KINDS:
        raise LoadRefused(f"kind must be one of {', '.join(DOCUMENT_KINDS)}")
    ticker = ticker.upper()
    ids = instrument_ids(session, [ticker])
    if ticker not in ids:
        raise LoadRefused(f"no instrument for {ticker}; add the symbol first")
    when, assumed = resolve_available_at(ticker, on=on, available_at=available_at)
    report = LoadReport(ticker, kind, when, assumed, apply)
    for path in paths:
        result = FileResult(str(path), "refused")
        report.files.append(result)
        content_type = content_type_for(path)
        result.content_type = content_type
        if content_type is None:
            result.reason = "not a supported type (.html, .htm, .txt, .md)"
            continue
        try:
            data = path.read_bytes()
        except OSError as exc:
            result.reason = f"cannot read the file ({exc.__class__.__name__})"
            continue
        result.size_bytes = len(data)
        result.sha256 = sha256_of(data)
        try:
            extracted = extract(data, content_type)
        except ExtractError as exc:
            result.reason = str(exc)
            continue
        result.text_chars = len(extracted.text)
        existing = find_by_hash(session, result.sha256)
        if existing is not None:
            result.status = "duplicate"
            result.document_id = existing.id
            continue
        if not apply:
            result.status = "new"
            continue
        doc, _ = add_document(
            session,
            NewDocument(
                instrument_id=ids[ticker],
                kind=kind,
                source="file",
                title=title or path.stem.replace("_", " "),
                available_at=when,
                available_assumed=assumed,
                event_date=on,
                form_type=form_type,
            ),
            data,
            extracted,
        )
        session.commit()
        result.status = "stored"
        result.document_id = doc.id
    return report
