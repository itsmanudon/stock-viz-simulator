"""Read-only check that the ticker and the instrument key agree (Phase 4.6a).

The design note's step 3: before contracting, compare totals read through
each key. Through the ticker, a row belongs to ``symbols.ticker``; through
the instrument, it belongs to whatever symbol ``instrument_id`` resolves to
today (its current ``yahoo`` identifier). Per portfolio: positions, cost
basis and trades. Per symbol: daily bar count, first and last bar. Any line
that differs, or any NULL ``instrument_id``, fails the check.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import text
from sqlmodel import Session

from stockviz.services.instruments import TICKER_TABLES

_RESOLVED = (
    "JOIN instrument_identifiers x ON x.instrument_id = t.instrument_id "
    "AND x.scheme = 'yahoo' AND x.valid_to IS NULL"
)


@dataclass
class VerifyReport:
    nulls: dict[str, int] = field(default_factory=dict)
    portfolio_diffs: list[tuple] = field(default_factory=list)
    bar_diffs: list[tuple] = field(default_factory=list)
    portfolios: int = 0
    symbols_with_bars: int = 0

    @property
    def ok(self) -> bool:
        return not self.nulls and not self.portfolio_diffs and not self.bar_diffs


def _rows(session: Session, sql: str) -> dict:
    return {row[0]: tuple(row[1:]) for row in session.execute(text(sql)).all()}


def verify_identity(session: Session) -> VerifyReport:
    report = VerifyReport()
    for table in TICKER_TABLES:
        count = session.execute(
            text(f"SELECT count(*) FROM {table} WHERE ticker IS NOT NULL AND instrument_id IS NULL")
        ).scalar_one()
        if count:
            report.nulls[table] = count

    def portfolio_totals(join: str) -> dict:
        positions = _rows(
            session,
            "SELECT t.portfolio_id, count(*), sum(t.quantity * t.avg_cost) "
            f"FROM positions t {join} GROUP BY t.portfolio_id",
        )
        trades = _rows(
            session,
            f"SELECT t.portfolio_id, count(*) FROM trades t {join} GROUP BY t.portfolio_id",
        )
        keys = set(positions) | set(trades)
        return {k: (*positions.get(k, (0, None)), *trades.get(k, (0,))) for k in sorted(keys)}

    by_ticker = portfolio_totals("JOIN symbols s ON s.ticker = t.ticker")
    by_instrument = portfolio_totals(_RESOLVED)
    report.portfolios = len(by_ticker)
    for key in sorted(set(by_ticker) | set(by_instrument)):
        if by_ticker.get(key) != by_instrument.get(key):
            report.portfolio_diffs.append((key, by_ticker.get(key), by_instrument.get(key)))

    bars = "count(*), min(t.ts), max(t.ts) FROM price_bars t"
    ticker_bars = _rows(
        session,
        f"SELECT t.ticker, {bars} JOIN symbols s ON s.ticker = t.ticker "
        "WHERE t.interval = '1d' GROUP BY t.ticker",
    )
    instrument_bars = _rows(
        session, f"SELECT x.value, {bars} {_RESOLVED} WHERE t.interval = '1d' GROUP BY x.value"
    )
    report.symbols_with_bars = len(ticker_bars)
    for key in sorted(set(ticker_bars) | set(instrument_bars)):
        if ticker_bars.get(key) != instrument_bars.get(key):
            report.bar_diffs.append((key, ticker_bars.get(key), instrument_bars.get(key)))
    return report
