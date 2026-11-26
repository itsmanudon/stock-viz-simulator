"""Monthly partitions of ``intraday_bars`` on PostgreSQL (A6.1).

The parent is ``PARTITION BY RANGE (ts)``; each month is its own table,
``intraday_bars_yYYYYmMM``, ``FOR VALUES FROM (first of the month) TO (first
of the next)``. There is no default partition, so a row for a month without
one fails loudly rather than landing somewhere a retention drop would miss.
Writers call :func:`ensure_month_partitions` for the months they touch. A
retention window later drops whole partitions.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime

from sqlalchemy import text
from sqlalchemy.engine import Connection

from stockviz.models.intraday import PARTITION_PREFIX


def month_of(ts: datetime) -> date:
    return date(ts.year, ts.month, 1)


def _next_month(month: date) -> date:
    return date(month.year + (month.month == 12), month.month % 12 + 1, 1)


def partition_name(month: date) -> str:
    return f"{PARTITION_PREFIX}{month.year:04d}m{month.month:02d}"


def ensure_month_partitions(conn: Connection, months: Iterable[date]) -> list[str]:
    """Create the missing monthly partitions; return the names created. No-op off PostgreSQL."""
    if conn.dialect.name != "postgresql":
        return []
    wanted = sorted({date(m.year, m.month, 1) for m in months})
    if not wanted:
        return []
    existing = {
        row[0]
        for row in conn.execute(
            text(
                "SELECT c.relname FROM pg_inherits i JOIN pg_class c ON c.oid = i.inhrelid "
                "JOIN pg_class p ON p.oid = i.inhparent WHERE p.relname = 'intraday_bars'"
            )
        )
    }
    created: list[str] = []
    for month in wanted:
        name = partition_name(month)
        if name in existing:
            continue
        conn.execute(
            text(
                f'CREATE TABLE IF NOT EXISTS "{name}" PARTITION OF intraday_bars '
                f"FOR VALUES FROM ('{month.isoformat()}') TO ('{_next_month(month).isoformat()}')"
            )
        )
        created.append(name)
    return created
