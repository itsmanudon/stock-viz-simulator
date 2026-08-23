"""Throwaway PostgreSQL database for tests that need real locking.

CI sets ``DATABASE_URL`` to Postgres; locally these helpers no-op-skip only
when that env var is missing or is not a Postgres URL. Connection or DDL
failures must propagate — they are not skips.

``str(sqlalchemy.engine.URL)`` masks the password as ``***``. Engines are
created from the URL object (or ``render_as_string(hide_password=False)``)
so the scratch database actually authenticates.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy.engine import Engine, make_url
from sqlmodel import Session, SQLModel, create_engine, text

import stockviz.models  # noqa: F401 — register metadata

_SCRATCH_DB = "stockviz_lock_test"


def postgres_admin_url() -> str | None:
    """Return a psycopg URL if ``DATABASE_URL`` points at PostgreSQL, else None."""
    raw = os.environ.get("DATABASE_URL", "").strip()
    if not raw:
        return None
    if raw.startswith("postgres://"):
        raw = "postgresql+psycopg://" + raw[len("postgres://") :]
    elif raw.startswith("postgresql://"):
        raw = "postgresql+psycopg://" + raw[len("postgresql://") :]
    if "postgresql" not in raw:
        return None
    return raw


def _terminate_and_drop(conn, dbname: str) -> None:
    conn.execute(
        text(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = :d AND pid <> pg_backend_pid()"
        ),
        {"d": dbname},
    )
    conn.execute(text(f'DROP DATABASE IF EXISTS "{dbname}"'))


@contextmanager
def scratch_postgres_engine() -> Iterator[Engine]:
    """Yield an engine bound to a fresh database, then drop it.

    Caller must only invoke this when :func:`postgres_admin_url` is not None.
    """
    admin_url = postgres_admin_url()
    if admin_url is None:
        raise RuntimeError("scratch_postgres_engine requires a PostgreSQL DATABASE_URL")

    parsed = make_url(admin_url)
    admin = create_engine(parsed, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        _terminate_and_drop(conn, _SCRATCH_DB)
        conn.execute(text(f'CREATE DATABASE "{_SCRATCH_DB}"'))

    test_url = parsed.set(database=_SCRATCH_DB)
    engine = create_engine(test_url, pool_pre_ping=True)
    SQLModel.metadata.create_all(engine)
    try:
        yield engine
    finally:
        engine.dispose()
        with admin.connect() as conn:
            _terminate_and_drop(conn, _SCRATCH_DB)
        admin.dispose()


def session_on(engine: Engine) -> Session:
    return Session(engine)
