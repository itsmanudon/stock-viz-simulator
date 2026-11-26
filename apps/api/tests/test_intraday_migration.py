"""A6.1's migration (``a6b1c3d5e7f9``) on PostgreSQL: up, down, up.

The upgrade adds ``intraday_files`` and a range-partitioned ``intraday_bars``
with no partitions; the writer makes a month's partition on demand. The
downgrade drops both, partitions included (their rows reload from the
owner's files), and the upgrade runs again.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import date
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text

from stockviz.services.intraday.partitions import ensure_month_partitions
from stockviz.settings import get_settings
from tests.pg_scratch import postgres_admin_url, scratch_alembic_engine

pytestmark = pytest.mark.skipif(
    postgres_admin_url() is None, reason="DATABASE_URL is not PostgreSQL"
)

API_ROOT = Path(__file__).resolve().parents[1]
BEFORE = "c9d2e4f6a8b1"
THIS = "a6b1c3d5e7f9"


@pytest.fixture(autouse=True)
def _keep_logging() -> Iterator[None]:
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    disabled = {
        name: lg.disabled
        for name, lg in logging.root.manager.loggerDict.items()
        if isinstance(lg, logging.Logger)
    }
    yield
    root.handlers[:] = handlers
    root.setLevel(level)
    for name, lg in logging.root.manager.loggerDict.items():
        if isinstance(lg, logging.Logger):
            lg.disabled = disabled.get(name, False)


def _bar(conn, instrument_id: int, ts: str) -> None:
    conn.execute(
        text(
            "INSERT INTO intraday_bars (instrument_id, feed, interval, ts, open, high, low, "
            "close, volume, source, ingested_at, available_at) VALUES (:i, 'file', '1m', :ts, "
            "1, 1, 1, 1, 0, 'bulk_1m', now(), :ts)"
        ),
        {"i": instrument_id, "ts": ts},
    )


def test_a61_intraday_migration_up_down_up(monkeypatch) -> None:
    with scratch_alembic_engine() as engine:
        monkeypatch.setenv("DATABASE_URL", engine.url.render_as_string(hide_password=False))
        get_settings.cache_clear()
        try:
            config = Config(str(API_ROOT / "alembic.ini"))
            config.set_main_option("script_location", str(API_ROOT / "migrations"))
            command.upgrade(config, BEFORE)
            assert "intraday_bars" not in inspect(engine).get_table_names()
            command.upgrade(config, THIS)
            with engine.begin() as conn:
                kind = conn.execute(
                    text("SELECT relkind FROM pg_class WHERE relname = 'intraday_bars'")
                ).scalar_one()
                assert kind == "p"  # partitioned
                conn.execute(
                    text(
                        "INSERT INTO symbols (ticker, name, is_active, currency, created_at) "
                        "VALUES ('TCS.NS', 'TCS', true, 'INR', now())"
                    )
                )
                iid = conn.execute(
                    text(
                        "SELECT instrument_id FROM instrument_identifiers "
                        "WHERE scheme = 'yahoo' AND value = 'TCS.NS'"
                    )
                ).scalar_one()
                with pytest.raises(Exception, match="no partition"), conn.begin_nested():
                    _bar(conn, iid, "2025-11-25 03:45")
                assert ensure_month_partitions(conn, [date(2025, 11, 1)]) == [
                    "intraday_bars_y2025m11"
                ]
                assert ensure_month_partitions(conn, [date(2025, 11, 1)]) == []
                _bar(conn, iid, "2025-11-25 03:45")
            # A partition the writer made is not drift for autogenerate
            # (checked at head: later migrations stack on this one).
            command.upgrade(config, "head")
            command.check(config)
            command.downgrade(config, THIS)
            command.downgrade(config, BEFORE)
            names = set(inspect(engine).get_table_names())
            assert not {"intraday_bars", "intraday_files", "intraday_bars_y2025m11"} & names
            command.upgrade(config, THIS)
            assert {"intraday_bars", "intraday_files"} <= set(inspect(engine).get_table_names())
        finally:
            get_settings.cache_clear()
