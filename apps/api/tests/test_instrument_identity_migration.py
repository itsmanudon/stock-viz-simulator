"""Phase 4.3: instrument identity expand, on a real Postgres.

The upgrade seeds one instrument per symbol and backfills ``instrument_id``;
the triggers keep it filled for every later write, including the bulk
``price_bars`` upsert that bypasses the ORM; the downgrade removes it all.
"""

from __future__ import annotations

import os
import subprocess
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import inspect, text
from sqlmodel import Session

from tests.pg_scratch import postgres_admin_url, scratch_alembic_engine

pytestmark = pytest.mark.skipif(
    postgres_admin_url() is None, reason="DATABASE_URL is not PostgreSQL"
)

API_ROOT = Path(__file__).resolve().parents[1]
PREVIOUS = "99489c8896a9"
# The expand step itself: later steps move the bar key off the ticker (4.6b).
EXPAND = "686dcf74171b"
TS = datetime(2026, 1, 2)


def _alembic(engine, *args: str) -> None:
    env = os.environ.copy()
    env["DATABASE_URL"] = engine.url.render_as_string(hide_password=False)
    subprocess.run(
        ["uv", "run", "alembic", *args], check=True, cwd=API_ROOT, env=env, capture_output=True
    )


def _symbol(session: Session, ticker: str, currency: str, exchange: str | None) -> None:
    session.execute(
        text(
            "INSERT INTO symbols (ticker, name, exchange, currency, is_active, created_at) "
            "VALUES (:t, :t, :e, :c, true, :ts)"
        ),
        {"t": ticker, "e": exchange, "c": currency, "ts": TS},
    )


def _bar(session: Session, ticker: str, ts: datetime) -> None:
    session.execute(
        text(
            "INSERT INTO price_bars (ticker, ts, interval, open, high, low, close, volume, source, "
            "adjustment_semantics, session_scope) "
            "VALUES (:t, :ts, '1d', 1, 1, 1, 1, 1, 'test', 'split_adjusted', 'regular') "
            "ON CONFLICT (ticker, ts, interval) DO UPDATE SET close = EXCLUDED.close"
        ),
        {"t": ticker, "ts": ts},
    )


def _instrument_of(session: Session, table: str, ticker: str):
    return session.execute(
        text(f"SELECT instrument_id FROM {table} WHERE ticker = :t LIMIT 1"), {"t": ticker}
    ).scalar_one()


def _instrument(session: Session, ticker: str):
    return session.execute(
        text(
            "SELECT i.id, i.symbol, i.mic, i.country, i.currency, i.quote_unit, i.asset_type "
            "FROM instruments i JOIN instrument_identifiers x ON x.instrument_id = i.id "
            "WHERE x.scheme = 'yahoo' AND x.value = :t"
        ),
        {"t": ticker},
    ).one()


def test_expand_backfills_dual_writes_and_downgrades() -> None:
    with scratch_alembic_engine() as engine:
        _alembic(engine, "upgrade", PREVIOUS)
        with Session(engine) as session:
            _symbol(session, "AAPL", "USD", None)  # no metadata yet: Aegis venue list
            _symbol(session, "BARC.L", "GBP", "LSE")
            _symbol(session, "NIFTY50.NS", "INR", "NSE")
            _symbol(session, "SILVER", "USD", "COMMODITY")
            _bar(session, "AAPL", TS)
            _bar(session, "BARC.L", TS)
            session.commit()

        _alembic(engine, "upgrade", EXPAND)

        with Session(engine) as session:
            aapl = _instrument(session, "AAPL")
            assert aapl[1:] == ("AAPL", "XNAS", "US", "USD", "USD", "equity")
            barc = _instrument(session, "BARC.L")
            assert barc[1:] == ("BARC", "XLON", "GB", "GBP", "GBX", "equity")
            assert _instrument(session, "NIFTY50.NS")[2:] == ("XNSE", "IN", "INR", "INR", "index")
            assert _instrument(session, "SILVER")[2:] == (None, None, "USD", "USD", "commodity")
            aegis = (
                session.execute(
                    text(
                        "SELECT value FROM instrument_identifiers WHERE scheme = 'aegis' ORDER BY 1"
                    )
                )
                .scalars()
                .all()
            )
            assert "stockviz:BARC.L" in aegis

            # Backfill.
            assert _instrument_of(session, "price_bars", "AAPL") == aapl[0]
            assert _instrument_of(session, "price_bars", "BARC.L") == barc[0]

            # Dual write: a bulk upsert, a new symbol and its first bar.
            _bar(session, "AAPL", datetime(2026, 1, 5))
            _symbol(session, "SAP.DE", "EUR", "GER")
            _bar(session, "SAP.DE", TS)
            session.execute(
                text(
                    "INSERT INTO users (email, name, created_at) VALUES ('id@stockviz.dev', 'Id', :ts)"
                ),
                {"ts": TS},
            )
            session.execute(
                text(
                    "INSERT INTO portfolios (user_id, name, cash_balance, created_at) "
                    "SELECT id, 'Default', 1000, :ts FROM users"
                ),
                {"ts": TS},
            )
            session.execute(
                text(
                    "INSERT INTO trades (portfolio_id, ticker, side, quantity, price, ts) "
                    "SELECT id, 'BARC.L', 'BUY', 1, :p, :ts FROM portfolios"
                ),
                {"p": Decimal("4.30"), "ts": TS},
            )
            session.commit()

            sap = _instrument(session, "SAP.DE")
            assert sap[1:3] == ("SAP", "XETR")
            new_bar = session.execute(
                text("SELECT instrument_id FROM price_bars WHERE ticker = 'AAPL' AND ts = :ts"),
                {"ts": datetime(2026, 1, 5)},
            ).scalar_one()
            assert new_bar == aapl[0]
            assert _instrument_of(session, "price_bars", "SAP.DE") == sap[0]
            assert _instrument_of(session, "trades", "BARC.L") == barc[0]

            # metadata filling an exchange later fills a missing venue.
            _symbol(session, "NEWCO", "USD", None)
            session.commit()
            assert _instrument(session, "NEWCO")[2] is None
            session.execute(text("UPDATE symbols SET exchange = 'NYQ' WHERE ticker = 'NEWCO'"))
            session.commit()
            assert _instrument(session, "NEWCO")[2:4] == ("XNYS", "US")

        _alembic(engine, "downgrade", PREVIOUS)
        inspector = inspect(engine)
        assert "instruments" not in inspector.get_table_names()
        assert "instrument_id" not in {c["name"] for c in inspector.get_columns("price_bars")}

        # Re-upgrade re-seeds from symbols.
        _alembic(engine, "upgrade", EXPAND)
        with Session(engine) as session:
            count = session.execute(text("SELECT count(*) FROM instruments")).scalar_one()
            assert count == 6
            missing = session.execute(
                text("SELECT count(*) FROM price_bars WHERE instrument_id IS NULL")
            ).scalar_one()
            assert missing == 0
