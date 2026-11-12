"""Phase 4.6a: the identity verification report, and instrument_id NOT NULL."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, SQLModel

from stockviz.models import Portfolio, Position, PriceBar, Symbol, Trade, TradeSide, User
from stockviz.services.instruments.verify import verify_identity
from tests.pg_scratch import postgres_admin_url, scratch_postgres_engine


def _bar(ticker: str, day: int) -> PriceBar:
    one = Decimal(1)
    return PriceBar(
        ticker=ticker,
        ts=datetime(2026, 11, day),
        interval="1d",
        open=one,
        high=one,
        low=one,
        close=one,
        volume=1,
        source="test",
    )


def _book(session: Session) -> int:
    session.add(Symbol(ticker="AAPL", name="Apple", currency="USD"))
    session.add(Symbol(ticker="SAP.DE", name="SAP", currency="EUR"))
    user = User(email="verify@stockviz.dev", name="V")
    session.add(user)
    session.commit()
    assert user.id is not None
    portfolio = Portfolio(user_id=user.id, name="Main", cash_balance=Decimal(1000))
    session.add(portfolio)
    session.commit()
    assert portfolio.id is not None
    for ticker in ("AAPL", "SAP.DE"):
        session.add(
            Position(
                portfolio_id=portfolio.id, ticker=ticker, quantity=Decimal(2), avg_cost=Decimal(5)
            )
        )
        session.add(
            Trade(
                portfolio_id=portfolio.id,
                ticker=ticker,
                side=TradeSide.BUY,
                quantity=Decimal(2),
                price=Decimal(5),
            )
        )
        session.add(_bar(ticker, 9))
        session.add(_bar(ticker, 10))
    session.commit()
    return portfolio.id


def test_matching_keys_verify(session: Session) -> None:
    _book(session)
    report = verify_identity(session)
    assert report.ok
    assert report.portfolios == 1 and report.symbols_with_bars == 2


def test_a_row_on_the_wrong_instrument_fails(session: Session) -> None:
    portfolio_id = _book(session)
    sap = session.execute(
        text("SELECT instrument_id FROM instrument_identifiers WHERE value = 'SAP.DE'")
    ).scalar_one()
    session.execute(
        text(
            "UPDATE price_bars SET instrument_id = :i WHERE ticker = 'AAPL' AND ts < '2026-11-10'"
        ),
        {"i": sap},
    )
    session.execute(text("UPDATE trades SET instrument_id = NULL WHERE ticker = 'AAPL'"))
    report = verify_identity(session)

    assert not report.ok
    assert report.nulls == {"trades": 1}
    assert [d[0] for d in report.portfolio_diffs] == [portfolio_id]
    assert {d[0] for d in report.bar_diffs} == {"AAPL", "SAP.DE"}


@pytest.mark.skipif(postgres_admin_url() is None, reason="DATABASE_URL is not PostgreSQL")
def test_postgres_refuses_a_row_without_an_instrument() -> None:
    with scratch_postgres_engine() as engine, Session(engine) as session:
        _book(session)
        assert verify_identity(session).ok  # the BEFORE trigger filled every row
        with pytest.raises(IntegrityError):
            session.execute(text("UPDATE positions SET instrument_id = NULL"))
        session.rollback()
        nullable = (
            session.execute(
                text(
                    "SELECT table_name FROM information_schema.columns "
                    "WHERE column_name = 'instrument_id' AND is_nullable = 'YES' "
                    "AND table_schema = current_schema()"
                )
            )
            .scalars()
            .all()
        )
        assert nullable == ["news_articles"]


def test_required_columns_cover_every_ticker_table_but_news() -> None:
    from stockviz.services.instruments import TICKER_TABLES

    required = {
        t for t in TICKER_TABLES if SQLModel.metadata.tables[t].c.instrument_id.nullable is False
    }
    assert required == set(TICKER_TABLES) - {"news_articles"}
