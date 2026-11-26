"""Measured size of ``intraday_bars`` (A6.1): ``stockviz.cli intraday-size``.

PostgreSQL only. The partitioned parent holds no rows itself, so sizes are
summed over its partitions: heap (with TOAST and the free-space and
visibility maps) and indexes separately, then bytes per row = total / rows.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.engine import Connection


@dataclass
class SizeReport:
    partitions: int
    rows: int
    table_bytes: int
    index_bytes: int
    per_symbol: list[tuple[str, str, int]] = field(default_factory=list)  # ticker, interval, rows

    @property
    def total_bytes(self) -> int:
        return self.table_bytes + self.index_bytes

    @property
    def bytes_per_row(self) -> float | None:
        return self.total_bytes / self.rows if self.rows else None


def measure(conn: Connection) -> SizeReport:
    if conn.dialect.name != "postgresql":
        raise RuntimeError("intraday-size measures PostgreSQL only")
    parts = conn.execute(
        text(
            "SELECT count(*), coalesce(sum(pg_table_size(relid)), 0), "
            "coalesce(sum(pg_indexes_size(relid)), 0) "
            "FROM pg_partition_tree('intraday_bars') WHERE isleaf"
        )
    ).one()
    per_symbol = conn.execute(
        text(
            "SELECT coalesce(ii.value, '#' || b.instrument_id::text), b.interval, count(*) "
            "FROM intraday_bars b LEFT JOIN instrument_identifiers ii "
            "ON ii.instrument_id = b.instrument_id AND ii.scheme = 'yahoo' AND ii.valid_to IS NULL "
            "GROUP BY 1, 2 ORDER BY 1, 2"
        )
    ).all()
    rows = sum(int(r[2]) for r in per_symbol)
    return SizeReport(
        partitions=int(parts[0]),
        rows=rows,
        table_bytes=int(parts[1]),
        index_bytes=int(parts[2]),
        per_symbol=[(str(t), str(i), int(n)) for t, i, n in per_symbol],
    )
