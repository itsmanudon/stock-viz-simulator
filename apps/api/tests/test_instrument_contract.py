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
    # Under the instrument key a bar cannot sit on a day SAP already has, so
    # drop SAP's first bar and move AAPL's onto SAP's instrument in its place.
    session.execute(text("DELETE FROM price_bars WHERE ticker = 'SAP.DE' AND ts < '2026-11-10'"))
    session.execute(
        text(
            "UPDATE price_bars SET instrument_id = :i WHERE ticker = 'AAPL' AND ts < '2026-11-10'"
        ),
        {"i": sap},
    )
    # NOT NULL holds on SQLite too since 4.6b; point a trade at an instrument
    # with no current ticker instead, so it vanishes from the instrument side.
    session.execute(
        text(
            "INSERT INTO instruments (symbol, currency, quote_unit, asset_type, status, created_at) "
            "VALUES ('GONE', 'USD', 'USD', 'equity', 'inactive', '2026-11-12')"
        )
    )
    session.execute(
        text(
            "UPDATE trades SET instrument_id = (SELECT id FROM instruments WHERE symbol = 'GONE') "
            "WHERE ticker = 'AAPL'"
        )
    )
    report = verify_identity(session)

    assert not report.ok
    assert report.nulls == {}
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
        # Phase 7.1: portfolio alert rules watch the account, not a ticker.
        assert nullable == ["alerts", "news_articles"]


def test_required_columns_cover_every_ticker_table_but_news() -> None:
    from stockviz.services.instruments import TICKER_TABLES

    required = {
        t for t in TICKER_TABLES if SQLModel.metadata.tables[t].c.instrument_id.nullable is False
    }
    assert required == set(TICKER_TABLES) - {"news_articles", "alerts"}


# --- Phase 4.6b: writers set instrument_id; keys are the instrument --------------


def test_the_orm_sets_instrument_id_before_the_insert(session: Session) -> None:
    session.add(Symbol(ticker="AAPL", name="Apple"))
    bar = _bar("AAPL", 9)
    session.add(bar)  # same flush as its symbol
    session.flush()
    in_memory = bar.__dict__["instrument_id"]  # before any expiry or reload

    known = session.execute(
        text("SELECT instrument_id FROM instrument_identifiers WHERE value = 'AAPL'")
    ).scalar_one()
    # Set in Python by the write hook, not read back from a trigger.
    assert in_memory == known


def test_a_watchlist_row_is_keyed_by_instrument(session: Session) -> None:
    from sqlalchemy import inspect as sa_inspect

    from stockviz.models import Watchlist, WatchlistItem

    _book(session)
    user_id = session.execute(text("SELECT id FROM users")).scalar_one()
    watchlist = Watchlist(user_id=user_id, name="W")
    session.add(watchlist)
    session.commit()
    item = WatchlistItem(watchlist_id=watchlist.id, ticker="SAP.DE")  # type: ignore[arg-type]
    session.add(item)
    session.commit()

    state = sa_inspect(item)
    assert state is not None
    key = state.identity
    assert key is not None and key[1] == item.instrument_id


@pytest.mark.skipif(postgres_admin_url() is None, reason="DATABASE_URL is not PostgreSQL")
def test_postgres_reingest_updates_under_the_instrument_key() -> None:
    from stockviz.services.ingest.bar_semantics import AdjustmentSemantics, SessionScope
    from stockviz.services.ingest.prices import BarRecord, write_accepted_bars

    def record(close: str) -> BarRecord:
        value = Decimal(close)
        return BarRecord(
            ticker="AAPL",
            ts=datetime(2026, 11, 9),
            interval="1d",
            open=value,
            high=value,
            low=value,
            close=value,
            volume=Decimal(1),
            source="yfinance",
            adjustment_semantics=AdjustmentSemantics.SPLIT_ADJUSTED,
            session_scope=SessionScope.REGULAR,
        )

    with scratch_postgres_engine() as engine, Session(engine) as session:
        session.add(Symbol(ticker="AAPL", name="Apple"))
        session.commit()
        write_accepted_bars(session, [record("1")])
        write_accepted_bars(session, [record("2")])
        session.commit()
        rows = session.execute(text("SELECT close FROM price_bars")).scalars().all()
        assert rows == [Decimal("2.000000")]
        pk = session.execute(
            text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conname = 'price_bars_pkey'"
            )
        ).scalar_one()
        assert pk == 'PRIMARY KEY (instrument_id, ts, "interval")'
