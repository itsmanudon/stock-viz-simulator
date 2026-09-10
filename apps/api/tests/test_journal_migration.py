"""Execute the journal migration against legacy rows, including PostgreSQL enums."""

from __future__ import annotations

import importlib.util
from decimal import Decimal
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import DBAPIError

from tests.pg_scratch import postgres_admin_url, scratch_alembic_engine


def _verify(engine, monkeypatch):
    source = (
        Path(__file__).resolve().parents[1]
        / "migrations/versions/a4d7c19f6e02_add_options_realization_and_journal_indexes.py"
    )
    spec = importlib.util.spec_from_file_location("journal_migration", source)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    basis_spec = importlib.util.spec_from_file_location(
        "basis_migration", source.with_name("b6e8a20f4c31_capture_equity_fill_cost_basis.py")
    )
    assert basis_spec is not None and basis_spec.loader is not None
    basis_migration = importlib.util.module_from_spec(basis_spec)
    basis_spec.loader.exec_module(basis_migration)
    with engine.begin() as connection:
        status_type = "VARCHAR"
        if engine.dialect.name == "postgresql":
            connection.execute(
                text(
                    "CREATE TYPE journal_test_status AS ENUM ('OPEN', 'CLOSED', 'EXPIRED', 'EXERCISED')"
                )
            )
            status_type = "journal_test_status"
        connection.execute(
            text("CREATE TABLE trades (id INTEGER PRIMARY KEY, portfolio_id INTEGER, ts TIMESTAMP)")
        )
        connection.execute(text("INSERT INTO trades (id, portfolio_id) VALUES (1, 7)"))
        connection.execute(
            text(
                f"CREATE TABLE options_positions (id INTEGER PRIMARY KEY, user_id INTEGER, settled_at TIMESTAMP, status {status_type}, premium_paid NUMERIC(20,6))"
            )
        )
        for index, status in enumerate(["OPEN", "CLOSED", "EXPIRED", "EXERCISED"], 1):
            connection.execute(
                text(
                    "INSERT INTO options_positions (id,user_id,status,premium_paid) VALUES (:id,1,:status,12.345678)"
                ),
                {"id": index, "status": status},
            )
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
        monkeypatch.setattr(
            basis_migration, "op", Operations(MigrationContext.configure(connection))
        )
        migration.upgrade()
        heap_before = (
            connection.execute(text("SELECT pg_relation_filenode('trades')")).scalar_one()
            if engine.dialect.name == "postgresql"
            else None
        )
        basis_migration.upgrade()
        if heap_before is not None:
            assert (
                connection.execute(text("SELECT pg_relation_filenode('trades')")).scalar_one()
                == heap_before
            )
        basis_column = next(
            column
            for column in inspect(connection).get_columns("trades")
            if column["name"] == "avg_cost_at_fill"
        )
        assert basis_column["nullable"] is True
        assert basis_column["default"] is None
        assert basis_column["type"].precision == 18
        assert basis_column["type"].scale == 6
        assert (
            connection.execute(text("SELECT avg_cost_at_fill FROM trades WHERE id=1")).scalar_one()
            is None
        )
        # An old writer omitting the new field remains compatible after upgrade.
        connection.execute(text("INSERT INTO trades (id, portfolio_id) VALUES (2, 8)"))
        assert (
            connection.execute(text("SELECT avg_cost_at_fill FROM trades WHERE id=2")).scalar_one()
            is None
        )
        connection.execute(text("UPDATE trades SET avg_cost_at_fill=123.456789 WHERE id=2"))
        assert Decimal(
            str(
                connection.execute(
                    text("SELECT avg_cost_at_fill FROM trades WHERE id=2")
                ).scalar_one()
            )
        ) == Decimal("123.456789")
        rows = connection.execute(
            text("SELECT status, proceeds, realized_pnl FROM options_positions ORDER BY id")
        ).all()
        assert rows[2][1] == 0
        assert float(rows[2][2]) == -12.345678
        assert all(row[2] is None for index, row in enumerate(rows) if index != 2)
        assert "avg_cost_at_fill" in {
            column["name"] for column in inspect(connection).get_columns("trades")
        }
        assert "ix_trades_portfolio_ts" in {
            index["name"] for index in inspect(connection).get_indexes("trades")
        }
        basis_migration.downgrade()
        assert connection.execute(
            text("SELECT id, portfolio_id FROM trades ORDER BY id")
        ).all() == [(1, 7), (2, 8)]
        migration.downgrade()
        assert "avg_cost_at_fill" not in {
            column["name"] for column in inspect(connection).get_columns("trades")
        }
        migration.upgrade()
        basis_migration.upgrade()
        # Downgrade is data-destructive for this field; re-upgrade cannot restore it.
        assert connection.execute(
            text("SELECT avg_cost_at_fill FROM trades ORDER BY id")
        ).scalars().all() == [None, None]
        assert connection.execute(text("SELECT COUNT(*) FROM options_positions")).scalar_one() == 4


def test_journal_migration_backfill_and_round_trip(monkeypatch):
    engine = create_engine("sqlite://")
    try:
        _verify(engine, monkeypatch)
    finally:
        engine.dispose()


@pytest.mark.skipif(postgres_admin_url() is None, reason="DATABASE_URL is not PostgreSQL")
def test_journal_migration_postgres_enum_and_indexes(monkeypatch):
    with scratch_alembic_engine() as engine:
        _verify(engine, monkeypatch)


@pytest.mark.skipif(postgres_admin_url() is None, reason="DATABASE_URL is not PostgreSQL")
def test_basis_migration_lock_timeout_is_atomic_and_retryable(monkeypatch):
    source = (
        Path(__file__).resolve().parents[1]
        / "migrations/versions/b6e8a20f4c31_capture_equity_fill_cost_basis.py"
    )
    spec = importlib.util.spec_from_file_location("basis_lock_migration", source)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with scratch_alembic_engine() as engine:
        with engine.begin() as setup:
            setup.execute(text("CREATE TABLE trades (id INTEGER PRIMARY KEY)"))
            setup.execute(text("INSERT INTO trades VALUES (1)"))
        # Even an ordinary reader holds a conflicting lock until its transaction ends.
        with engine.connect() as reader:
            reader.execute(text("SELECT * FROM trades")).all()
            with pytest.raises(DBAPIError) as blocked, engine.begin() as writer:
                writer.execute(text("SET LOCAL lock_timeout='200ms'"))
                monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(writer)))
                migration.upgrade()
            assert getattr(blocked.value.orig, "sqlstate", None) == "55P03"
            reader.rollback()
        with engine.begin() as writer:
            assert "avg_cost_at_fill" not in {
                column["name"] for column in inspect(writer).get_columns("trades")
            }
            writer.execute(text("SET LOCAL lock_timeout='2s'"))
            monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(writer)))
            migration.upgrade()
            assert (
                writer.execute(
                    text(
                        "SELECT count(*) FROM pg_locks WHERE pid=pg_backend_pid() "
                        "AND relation='trades'::regclass AND mode='AccessExclusiveLock' AND granted"
                    )
                ).scalar_one()
                == 1
            )
            assert writer.execute(text("SELECT avg_cost_at_fill FROM trades")).scalar_one() is None
