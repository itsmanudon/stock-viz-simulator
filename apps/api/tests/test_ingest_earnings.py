"""Provider-normalization and idempotency checks for earnings ingestion."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlmodel import Session, select

from stockviz.models import EarningsEvent, Symbol
from stockviz.services.ingest.earnings import ingest_earnings_for_ticker, parse_earnings_rows


class _Rows:
    empty = False

    def __init__(self, rows):
        self.rows = rows

    def iterrows(self):
        return iter(self.rows)


def test_parse_earnings_rows_normalizes_estimates_and_schedule() -> None:
    rows = _Rows(
        [
            (
                "2026-10-28",
                {"EPS Estimate": "1.20", "Reported EPS": None, "When": "AMC"},
            )
        ]
    )
    parsed = parse_earnings_rows("aapl", rows)
    assert parsed[0].ticker == "AAPL"
    assert parsed[0].event_date == date(2026, 10, 28)
    assert parsed[0].eps_estimate == Decimal("1.20")
    assert parsed[0].report_time == "AMC"


def test_ingest_earnings_is_idempotent_and_updates_actual(session: Session) -> None:
    session.add(Symbol(ticker="AAPL", name="Apple Inc."))
    session.commit()

    pending = _Rows([("2026-10-28", {"EPS Estimate": "1.20", "Reported EPS": None, "When": "AMC"})])
    assert ingest_earnings_for_ticker(session, "AAPL", fetch_fn=lambda _ticker: pending) == 1
    assert ingest_earnings_for_ticker(session, "AAPL", fetch_fn=lambda _ticker: pending) == 0

    reported = _Rows(
        [("2026-10-28", {"EPS Estimate": "1.20", "Reported EPS": "1.30", "When": "AMC"})]
    )
    assert ingest_earnings_for_ticker(session, "AAPL", fetch_fn=lambda _ticker: reported) == 1
    event = session.exec(select(EarningsEvent)).one()
    assert event.eps_actual == Decimal("1.30")
