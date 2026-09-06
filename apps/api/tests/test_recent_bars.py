"""Bounded daily inputs retain the old window-query semantics."""

from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import event
from sqlalchemy.dialects import postgresql
from sqlmodel import Session

from stockviz.models import PriceBar, Symbol
from stockviz.routers.screener import _momentum_by_ticker
from stockviz.services.recent_bars import recent_closes, recent_closes_statement
from tests.pg_scratch import postgres_admin_url, scratch_postgres_engine


def seed(session: Session) -> None:
    session.add(Symbol(ticker="OLD", name="Inactive", is_active=False))
    session.add(Symbol(ticker="SHORT", name="Short"))
    session.add(Symbol(ticker="EMPTY", name="Empty"))
    session.flush()
    for ticker, closes in (("OLD", ["0", "1.123456", "2.234567", "3.345678"]), ("SHORT", ["0"])):
        for i, close in enumerate(closes):
            value = Decimal(close)
            session.add(
                PriceBar(
                    ticker=ticker,
                    ts=datetime(2025, 1, 1) + timedelta(days=i),
                    interval="1d",
                    open=value,
                    high=value,
                    low=value,
                    close=value,
                    volume=1,
                    source="test",
                )
            )
    session.add(
        PriceBar(
            ticker="OLD",
            ts=datetime(2026, 1, 1),
            interval="1h",
            open=Decimal(999),
            high=Decimal(999),
            low=Decimal(999),
            close=Decimal(999),
            volume=1,
            source="test",
        )
    )
    session.commit()


def verify(session: Session) -> None:
    seed(session)
    queries = []

    def record(conn, cursor, statement, parameters, context, executemany):
        queries.append(statement)

    event.listen(session.get_bind(), "before_cursor_execute", record)
    try:
        assert recent_closes(session, [], limit_per_ticker=2) == {}
        assert not queries
        assert recent_closes(
            session, ["OLD", "OLD", "SHORT", "EMPTY", "MISSING"], limit_per_ticker=2
        ) == {"OLD": [Decimal("2.234567"), Decimal("3.345678")], "SHORT": [Decimal(0)]}
        assert len(queries) == 1
        assert recent_closes(session, ["OLD"], limit_per_ticker=1) == {"OLD": [Decimal("3.345678")]}
        assert _momentum_by_ticker(session, ["OLD", "SHORT", "EMPTY"], days=2) == {
            "OLD": float((Decimal("3.345678") - Decimal("1.123456")) / Decimal("1.123456") * 100),
            "SHORT": None,
            "EMPTY": None,
        }
        assert _momentum_by_ticker(session, ["OLD"], days=3) == {"OLD": None}
        assert _momentum_by_ticker(session, ["OLD"], days=4) == {"OLD": None}
    finally:
        event.remove(session.get_bind(), "before_cursor_execute", record)


def test_recent_closes_sqlite(session: Session) -> None:
    verify(session)


def test_postgres_statement_bounds_each_ticker() -> None:
    sql = str(
        recent_closes_statement(["OLD"], 30, dialect="postgresql").compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    assert "JOIN LATERAL" in sql
    assert "LIMIT 30" in sql
    assert "row_number" not in sql
    assert "is_active" not in sql


@pytest.mark.skipif(postgres_admin_url() is None, reason="DATABASE_URL is not PostgreSQL")
def test_recent_closes_postgres() -> None:
    with scratch_postgres_engine() as engine, Session(engine) as session:
        verify(session)
