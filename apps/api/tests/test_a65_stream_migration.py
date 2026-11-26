"""A6.5's migration (``c8d3e5f7a9b2``) on PostgreSQL: up, down, up.

The upgrade lets ``intraday_bars.feed`` be ``replayed`` (on the partitioned
parent, so on every partition) and adds ``feed_streams``. The downgrade
refuses while a replayed bar is stored.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text

from stockviz.services.intraday.partitions import ensure_month_partitions
from stockviz.services.stream.hub import CHANNEL
from stockviz.settings import get_settings
from tests.pg_scratch import postgres_admin_url, scratch_alembic_engine
from tests.test_intraday_migration import _keep_logging  # noqa: F401

pytestmark = pytest.mark.skipif(
    postgres_admin_url() is None, reason="DATABASE_URL is not PostgreSQL"
)

API_ROOT = Path(__file__).resolve().parents[1]
BEFORE = "b7c2d4e6f8a1"
THIS = "c8d3e5f7a9b2"


def _bar(conn, instrument_id: int, feed: str) -> None:
    conn.execute(
        text(
            "INSERT INTO intraday_bars (instrument_id, feed, interval, ts, open, high, low, "
            "close, volume, source, ingested_at, available_at) VALUES (:i, :f, '1m', "
            "'2025-11-25 03:45', 1, 1, 1, 1, 0, 'replay_file', now(), '2025-11-25 03:46')"
        ),
        {"i": instrument_id, "f": feed},
    )


def test_a65_migration_up_down_up(monkeypatch) -> None:
    with scratch_alembic_engine() as engine:
        monkeypatch.setenv("DATABASE_URL", engine.url.render_as_string(hide_password=False))
        get_settings.cache_clear()
        try:
            config = Config(str(API_ROOT / "alembic.ini"))
            config.set_main_option("script_location", str(API_ROOT / "migrations"))
            command.upgrade(config, BEFORE)
            with engine.begin() as conn:
                conn.execute(text(
                    "INSERT INTO symbols (ticker, name, is_active, currency, created_at) "
                    "VALUES ('TCS.NS', 'TCS', true, 'INR', now())"
                ))  # fmt: skip
                iid = conn.execute(text(
                    "SELECT instrument_id FROM instrument_identifiers "
                    "WHERE scheme = 'yahoo' AND value = 'TCS.NS'"
                )).scalar_one()  # fmt: skip
                ensure_month_partitions(conn, [date(2025, 11, 1)])
                with pytest.raises(Exception, match="ck_intraday_bars_feed"), conn.begin_nested():
                    _bar(conn, iid, "replayed")
            command.upgrade(config, THIS)
            assert "feed_streams" in inspect(engine).get_table_names()
            with engine.begin() as conn:
                _bar(conn, iid, "replayed")  # the existing partition takes it
                with pytest.raises(Exception, match="ck_intraday_bars_feed"), conn.begin_nested():
                    _bar(conn, iid, "live")
                conn.execute(text(
                    "INSERT INTO feed_streams (name, label, state, symbols, started_at, "
                    "updated_at) VALUES ('simulated', 'Replayed', 'closed', '[]', now(), now())"
                ))  # fmt: skip
                with pytest.raises(Exception, match="ck_feed_streams_state"), conn.begin_nested():
                    conn.execute(text("UPDATE feed_streams SET state = 'live'"))
                # NOTIFY on the channel the worker uses is accepted.
                conn.execute(text("SELECT pg_notify(:c, '{}')"), {"c": CHANNEL})
            # The models match the head schema (later revisions add tables, so
            # check at head and come back).
            command.upgrade(config, "head")
            command.check(config)
            command.downgrade(config, THIS)
            with pytest.raises(RuntimeError, match="replayed intraday bars"):
                command.downgrade(config, BEFORE)
            with engine.begin() as conn:
                conn.execute(text("DELETE FROM intraday_bars WHERE feed = 'replayed'"))
            command.downgrade(config, BEFORE)
            assert "feed_streams" not in inspect(engine).get_table_names()
            command.upgrade(config, THIS)
            assert "feed_streams" in inspect(engine).get_table_names()
        finally:
            get_settings.cache_clear()


def test_listen_hands_a_notified_bar_to_subscribers() -> None:
    """The API's hub hears a ``NOTIFY intraday_bar`` from another connection."""
    import asyncio

    import psycopg

    from stockviz.services.stream.hub import BarEvent, BarHub, listen_dsn

    url = postgres_admin_url()
    assert url is not None
    dsn = listen_dsn(url)
    assert dsn is not None
    event = BarEvent(ticker="TCS.NS", feed="replayed", badge="Replayed", interval="1m",
                     ts="2024-11-05T03:45:00Z", closed_at="2024-11-05T03:46:00Z", open="1",
                     high="1", low="1", close="1", volume=5, replayed=True)  # fmt: skip

    async def scenario() -> BarEvent:
        hub = BarHub(dsn)
        sub = hub.subscribe(["TCS.NS"])
        try:
            for _ in range(50):  # until the listener is up
                with psycopg.connect(dsn, autocommit=True) as conn:
                    conn.execute("SELECT pg_notify(%s, %s)", (CHANNEL, event.json()))
                try:
                    return await asyncio.wait_for(sub.queue.get(), timeout=0.2)
                except TimeoutError:
                    continue
            raise AssertionError("no notification arrived")
        finally:
            hub.unsubscribe(sub)

    assert asyncio.run(scenario()) == event
