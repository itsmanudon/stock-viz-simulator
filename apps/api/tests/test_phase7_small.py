"""Phase 7.5: RS-10 (moved earnings dates), SR-8 (signal bar dates),
OP-9 (request ids in API logs), OP-12 (outbox order per key, attempt cap)."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from stockviz._time import utcnow
from stockviz.events.outbox import (
    MAX_PUBLISH_ATTEMPTS,
    dead_events,
    enqueue_event,
    publish_batch,
)
from stockviz.logging_setup import REQUEST_ID, RequestIdFilter
from stockviz.models import EarningsEvent, OutboxEvent, PriceBar, Recommendation, Symbol
from stockviz.services.ingest.earnings import duplicate_upcoming, ingest_earnings_for_ticker
from stockviz.services.recommend.engine import score_universe
from tests.test_ingest_earnings import _Rows

# --- RS-10 --------------------------------------------------------------------


def _upcoming(days: int) -> str:
    return (utcnow().date() + timedelta(days=days)).isoformat()


def test_a_moved_report_date_moves_the_row(session: Session) -> None:
    session.add(Symbol(ticker="AAPL", name="Apple"))
    session.commit()
    first = _Rows([(_upcoming(10), {"EPS Estimate": "1.20", "Reported EPS": None})])
    assert ingest_earnings_for_ticker(session, "AAPL", fetch_fn=lambda _t: first) == 1
    moved = _Rows([(_upcoming(17), {"EPS Estimate": "1.25", "Reported EPS": None})])
    ingest_earnings_for_ticker(session, "AAPL", fetch_fn=lambda _t: moved)

    (row,) = session.exec(select(EarningsEvent)).all()
    assert row.event_date.isoformat() == _upcoming(17)
    assert row.previous_date is not None and row.previous_date.isoformat() == _upcoming(10)
    assert row.eps_estimate == Decimal("1.25")
    assert duplicate_upcoming(session) == []


def test_a_far_new_date_is_a_new_report_and_old_duplicates_are_listed(session: Session) -> None:
    session.add(Symbol(ticker="AAPL", name="Apple"))
    session.commit()
    ingest_earnings_for_ticker(
        session, "AAPL", fetch_fn=lambda _t: _Rows([(_upcoming(10), {"Reported EPS": None})])
    )
    # 90 days on is the next quarter, not a move: the first row stays.
    ingest_earnings_for_ticker(
        session, "AAPL", fetch_fn=lambda _t: _Rows([(_upcoming(100), {"Reported EPS": None})])
    )
    assert len(session.exec(select(EarningsEvent)).all()) == 2
    # Two rows a week apart, as old moves left them, are reported (not removed).
    session.add(EarningsEvent(ticker="AAPL", event_date=utcnow().date() + timedelta(days=14)))
    session.commit()
    found = duplicate_upcoming(session)
    assert [t for t, _days in found] == ["AAPL"] and len(found[0][1]) == 2


# --- SR-8 ---------------------------------------------------------------------


def _bars(session: Session, ticker: str, last: datetime, n: int = 40) -> None:
    for i in range(n):
        c = Decimal(100 + (i % 5))
        session.add(
            PriceBar(
                ticker=ticker, ts=last - timedelta(days=n - 1 - i), interval="1d",
                open=c, high=c, low=c, close=c, volume=1000, source="test",
            )
        )  # fmt: skip


def test_signals_carry_their_bar_date_and_say_when_stale(
    session: Session, client: TestClient
) -> None:
    session.add_all([Symbol(ticker="AAPL", name="Apple"), Symbol(ticker="MSFT", name="Msft")])
    session.commit()
    _bars(session, "AAPL", datetime(2026, 11, 12))
    _bars(session, "MSFT", datetime(2026, 11, 2))  # stalled ten days earlier
    session.commit()
    score_universe(session, persist=True)
    stored = {r.ticker: r.bar_date for r in session.exec(select(Recommendation)).all()}
    assert stored["AAPL"].isoformat() == "2026-11-12"  # type: ignore[union-attr]
    rows = {r["ticker"]: r for r in client.get("/v1/recommendations").json()}
    assert rows["AAPL"]["bar_date"] == "2026-11-12" and rows["AAPL"]["stale"] is False
    assert rows["MSFT"]["bar_date"] == "2026-11-02" and rows["MSFT"]["stale"] is True


# --- OP-9 ---------------------------------------------------------------------


def test_every_response_carries_a_request_id(client: TestClient) -> None:
    made = client.get("/live")
    assert len(made.headers["X-Request-ID"]) == 32
    kept = client.get("/live", headers={"X-Request-ID": "web-abc_123"})
    assert kept.headers["X-Request-ID"] == "web-abc_123"
    replaced = client.get("/live", headers={"X-Request-ID": "bad id with spaces"})
    assert replaced.headers["X-Request-ID"] != "bad id with spaces"


def test_log_lines_name_the_request() -> None:
    record = logging.LogRecord("x", logging.INFO, __file__, 1, "hello", None, None)
    token = REQUEST_ID.set("req-42")
    try:
        RequestIdFilter().filter(record)
    finally:
        REQUEST_ID.reset(token)
    assert record.request_id == "req-42"  # type: ignore[attr-defined]
    RequestIdFilter().filter(record)
    assert record.request_id == "-"  # type: ignore[attr-defined]


# --- OP-12 --------------------------------------------------------------------


class _Broker:
    def __init__(self, failing_keys: set[str]) -> None:
        self.failing = failing_keys
        self.sent: list[tuple[str, int]] = []

    def publish(self, *, topic: str, key: str, value: dict) -> None:
        if key in self.failing:
            raise RuntimeError("broker refused")
        self.sent.append((key, value["n"]))


def _event(session: Session, key: str, n: int) -> None:
    enqueue_event(
        session, event_id=uuid4(), event_type="test.v1", schema_version=1,
        aggregate_type="t", aggregate_id=key, topic="t", partition_key=key,
        envelope={"n": n}, occurred_at=utcnow() + timedelta(microseconds=n),
    )  # fmt: skip
    session.flush()


def test_a_failed_event_holds_back_its_key_and_dies_after_the_cap(session: Session) -> None:
    for n, key in enumerate(["A", "B", "A", "B"]):
        _event(session, key, n)
    session.commit()
    broker = _Broker({"A"})
    assert publish_batch(session, broker, limit=10) == 2
    assert broker.sent == [("B", 1), ("B", 3)]  # the second A waited behind the first
    pending = session.exec(select(OutboxEvent).where(OutboxEvent.partition_key == "A")).all()
    assert sorted(e.publish_attempts for e in pending) == [0, 1]

    for _ in range(MAX_PUBLISH_ATTEMPTS):
        publish_batch(session, broker, limit=10)
    (dead,) = dead_events(session)
    assert dead.payload["n"] == 0 and dead.publish_attempts == MAX_PUBLISH_ATTEMPTS
    # Once the first A died it stopped holding its key: the second A is tried.
    second = session.exec(
        select(OutboxEvent).where(OutboxEvent.partition_key == "A", OutboxEvent.dead_at.is_(None))  # type: ignore[union-attr]
    ).one()
    assert second.publish_attempts == 2  # tried in the batch the first died, and the next
    broker.failing.clear()
    assert publish_batch(session, broker, limit=10) == 1  # dead rows are not claimed
    assert broker.sent[-1] == ("A", 2)
