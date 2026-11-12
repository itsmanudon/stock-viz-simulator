"""The SQLite test triggers derive the same instruments as Postgres (Phase 4.4a).

Tests run on SQLite, production on Postgres, and both build instruments from
``symbols`` by trigger (``stockviz/db_identity.py``). The two rule sets are
written twice, once per dialect, so this keeps them equal.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel

from stockviz.models import PriceBar, Symbol
from tests.pg_scratch import postgres_admin_url, scratch_postgres_engine

SYMBOLS = [
    ("AAPL", None, "USD"),
    ("JPM", None, "USD"),
    ("NEWCO", None, "USD"),
    ("MSFT", "NMS", "USD"),
    ("BAC", "NYQ", "USD"),
    ("BARC.L", "LSE", "GBP"),
    ("VOD.L", None, "GBP"),
    ("SAP.DE", "GER", "EUR"),
    ("SHOP.TO", "TOR", "CAD"),
    ("7203.T", "JPX", "JPY"),
    ("RELIANCE.NS", "NSI", "INR"),
    ("NIFTY50.NS", "NSE", "INR"),
    ("Nifty50.NS", "NSE", "INR"),
    ("BANKNIFTY.NS", "NSE", "INR"),
    ("SILVER", "COMMODITY", "USD"),
    ("HDFC.BO", None, "INR"),
]


def _instruments(engine) -> dict[str, tuple]:
    with Session(engine) as session:
        for ticker, exchange, currency in SYMBOLS:
            session.add(Symbol(ticker=ticker, name=ticker, exchange=exchange, currency=currency))
        session.commit()
        session.add(
            PriceBar(
                ticker="BARC.L",
                ts=datetime(2026, 1, 2),
                interval="1d",
                open=Decimal(1),
                high=Decimal(1),
                low=Decimal(1),
                close=Decimal(1),
                volume=1,
                source="test",
            )
        )
        session.commit()
        rows = session.execute(
            text(
                "SELECT x.value, i.symbol, i.mic, i.country, i.currency, i.quote_unit, "
                "i.asset_type, i.status FROM instruments i JOIN instrument_identifiers x "
                "ON x.instrument_id = i.id AND x.scheme = 'yahoo'"
            )
        ).all()
        bar = session.execute(
            text(
                "SELECT b.instrument_id = x.instrument_id FROM price_bars b JOIN "
                "instrument_identifiers x ON x.value = b.ticker AND x.scheme = 'yahoo'"
            )
        ).scalar_one()
        assert bar
    return {row[0]: tuple(row[1:]) for row in rows}


def _sqlite_engine():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)
    return engine


def test_sqlite_rules() -> None:
    got = _instruments(_sqlite_engine())
    assert got["AAPL"] == ("AAPL", "XNAS", "US", "USD", "USD", "equity", "active")
    assert got["BARC.L"] == ("BARC", "XLON", "GB", "GBP", "GBX", "equity", "active")
    assert got["7203.T"][:3] == ("7203", "XTKS", "JP")
    assert got["NEWCO"][1] is None
    assert got["BANKNIFTY.NS"][5] == "index"
    assert got["SILVER"][1:3] == (None, None)


@pytest.mark.skipif(postgres_admin_url() is None, reason="DATABASE_URL is not PostgreSQL")
def test_sqlite_matches_postgres() -> None:
    sqlite = _instruments(_sqlite_engine())
    with scratch_postgres_engine() as engine:
        postgres = _instruments(engine)
    assert sqlite == postgres
