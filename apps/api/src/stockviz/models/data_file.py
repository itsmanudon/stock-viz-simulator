"""Raw exchange files and what became of them (A1.1).

One ``data_files`` row per file handed to ``stockviz.cli nse-load --apply``:
where it came from, the session it is for, its SHA-256 (unique, so the same
file is recorded once), where the copy in the archive is, and the parse
result. The row never holds the file's contents; the archived copy does.
A1.2's downloader adds the URL it fetched.
"""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, Column, Text
from sqlmodel import Field, SQLModel

from stockviz._time import utcnow
from stockviz.models.instrument import ID_TYPE

PARSE_PARSED = "parsed"
PARSE_DATE_MISMATCH = "date_mismatch"
PARSE_UNRECOGNISED = "unrecognised"
PARSE_FAILED = "failed"
PARSE_STATUSES = (PARSE_PARSED, PARSE_DATE_MISMATCH, PARSE_UNRECOGNISED, PARSE_FAILED)


class DataFile(SQLModel, table=True):
    __tablename__ = "data_files"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        CheckConstraint(
            "parse_status IN ('parsed', 'date_mismatch', 'unrecognised', 'failed')",
            name="ck_data_files_parse_status",
        ),
    )

    id: int | None = Field(default=None, sa_column=Column(ID_TYPE, primary_key=True))
    # nse_cm_udiff, nse_cm_legacy, nse_sec_full; "unknown" when the header
    # matched no format.
    source: str = Field(max_length=32, index=True)
    trading_date: date_type | None = Field(default=None, index=True)
    file_name: str = Field(max_length=255)
    sha256: str = Field(max_length=64, unique=True)
    size_bytes: int = Field(sa_column=Column(BigInteger, nullable=False))
    archived_path: str = Field(max_length=512)
    received_at: datetime = Field(default_factory=utcnow, nullable=False)
    parse_status: str = Field(max_length=16)
    rows_total: int = Field(default=0)
    rows_loaded: int = Field(default=0)
    error: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
