"""Keep raw NSE files as received and record each one (A1.1).

A file is copied into ``NSE_ARCHIVE_DIR`` at ``<source>/<yyyy>/<file name>``
(``unknown`` for the year when the file carries no usable date) and gets one
``data_files`` row keyed by its SHA-256. A hash already recorded means the
file was handled before: nothing is copied or written again. The archive is
the input for every later re-parse; a file is never fetched twice. The row
never holds the file's contents.
"""

from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path

from sqlmodel import Session, col, select

from stockviz.models.data_file import DataFile
from stockviz.settings import get_settings


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def archive_root() -> Path:
    return Path(get_settings().nse_archive_dir)


def recorded_file(session: Session, sha256: str) -> DataFile | None:
    return session.exec(select(DataFile).where(col(DataFile.sha256) == sha256)).first()


def archive_copy(
    data: bytes, *, root: Path, source: str, trading_date: date | None, file_name: str
) -> Path:
    """Write ``data`` into the archive and return where it went.

    The same bytes already there are kept as they are. A different file with
    the same name (a re-publish) is stored beside it with the hash's first
    twelve characters added to the name, so nothing archived is overwritten.
    """
    folder = root / source / (str(trading_date.year) if trading_date else "unknown")
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / Path(file_name).name
    if target.exists():
        if sha256_hex(target.read_bytes()) == sha256_hex(data):
            return target
        name = Path(file_name).name
        stem, dot, ext = name.partition(".")
        target = folder / f"{stem}.{sha256_hex(data)[:12]}{dot}{ext}"
        if target.exists():
            return target
    tmp = target.with_name(target.name + ".part")
    tmp.write_bytes(data)
    tmp.replace(target)
    return target


def record_file(
    session: Session,
    *,
    source: str,
    trading_date: date | None,
    file_name: str,
    sha256: str,
    size_bytes: int,
    archived_path: Path,
    parse_status: str,
    rows_total: int = 0,
    rows_loaded: int = 0,
    error: str | None = None,
) -> DataFile:
    """Add the ``data_files`` row (flushed, so it has an id). The caller commits."""
    row = DataFile(
        source=source,
        trading_date=trading_date,
        file_name=Path(file_name).name,
        sha256=sha256,
        size_bytes=size_bytes,
        archived_path=str(archived_path),
        parse_status=parse_status,
        rows_total=rows_total,
        rows_loaded=rows_loaded,
        error=error[:2000] if error else None,
    )
    session.add(row)
    session.flush()
    return row
