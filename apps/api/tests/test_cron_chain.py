"""The nightly cron chain, run through the CLI at a frozen 22:00 UTC (audit OP-15).

The cron test elsewhere only matches text. This one reads the real chain
from ``.railway/railway.ts`` and runs each ``stockviz.cli`` step through the
CLI entry point, in order, against one database, with the providers stubbed.
It checks what a night must leave behind: today's session stored (MD-3), the
triggered order filled against it (P0-1), the alert fired (P0-2), the
snapshot dated by that session (LG-2) and every step recorded in
``job_runs`` (OP-5). It runs on SQLite, and on a scratch PostgreSQL database
when ``DATABASE_URL`` points at one.
"""

from __future__ import annotations

import re
import shlex
from collections.abc import Iterator
from datetime import datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, select

from stockviz import cli
from stockviz.models import (
    Alert,
    AlertDirection,
    JobRun,
    PendingOrder,
    PortfolioSnapshot,
    PriceBar,
    Symbol,
    User,
)
from stockviz.models.order import OrderStatus, OrderType
from stockviz.models.portfolio import TradeSide
from stockviz.services.trading import ensure_default_portfolio
from tests.pg_scratch import postgres_admin_url, scratch_postgres_engine
from tests.test_railway_cron import _code, _eod_refresh, _source

WEDNESDAY_CRON = datetime(2026, 11, 11, 22, 0)  # 17:00 EST: Wednesday is complete
WEDNESDAY = datetime(2026, 11, 11)
TUESDAY = datetime(2026, 11, 10)


def _chain_steps() -> list[list[str]]:
    """``stockviz.cli`` invocations in chain order, Monday-only steps included."""
    steps = []
    for invocation in re.findall(
        r"python -m stockviz\.cli ([^|;\"')]+)", _eod_refresh(_code(_source()))
    ):
        steps.append(shlex.split(invocation.strip()))
    return steps


def _bar(ticker: str, ts: datetime, close: str = "100") -> PriceBar:
    value = Decimal(close)
    return PriceBar(
        ticker=ticker,
        ts=ts,
        interval="1d",
        open=value,
        high=value,
        low=value,
        close=value,
        volume=1_000,
        source="test",
    )


@pytest.fixture(params=["sqlite", "postgres"])
def chain_engine(request) -> Iterator:
    if request.param == "sqlite":
        engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        SQLModel.metadata.create_all(engine)
        yield engine
        engine.dispose()
        return
    if postgres_admin_url() is None:
        pytest.skip("DATABASE_URL is not PostgreSQL")
    with scratch_postgres_engine() as engine:
        yield engine


def test_the_nightly_chain_leaves_the_night_it_should(chain_engine, monkeypatch) -> None:
    engine = chain_engine
    monkeypatch.setattr(cli, "engine", engine)
    monkeypatch.setattr("stockviz._time.utcnow", lambda: WEDNESDAY_CRON)

    # Providers stubbed: ingest returns Wednesday's bar, no other provider I/O.
    def fake_ingest(session: Session, ticker: str, **_kw) -> int:
        session.add(_bar(ticker, WEDNESDAY))
        session.commit()
        return 1

    monkeypatch.setattr(cli, "ingest_ticker", fake_ingest)
    monkeypatch.setattr(cli, "ingest_fx", lambda _s, _ccy: 1)
    monkeypatch.setattr(cli, "ingest_dividends_for_all", lambda _s, **_kw: {})
    monkeypatch.setattr(cli, "ingest_earnings_for_all", lambda _s, **_kw: {})
    monkeypatch.setattr(cli, "backfill_symbol_metadata", lambda _s, **_kw: {})
    monkeypatch.setattr(
        "stockviz.services.corporate_actions.splits._default_split_fetch", lambda _t: []
    )

    with Session(engine) as session:
        session.add(Symbol(ticker="AAPL", name="Apple"))
        user = User(email="night@stockviz.dev", name="Night")
        session.add(user)
        session.commit()
        session.add(_bar("AAPL", TUESDAY, "120"))
        session.commit()
        assert user.id is not None
        portfolio = ensure_default_portfolio(session, user.id)
        assert portfolio.id is not None
        order = PendingOrder(
            portfolio_id=portfolio.id,
            ticker="AAPL",
            side=TradeSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal(1),
            limit_price=Decimal(110),  # Tuesday 120 no; Wednesday 100 yes
        )
        alert = Alert(
            user_id=user.id,
            ticker="AAPL",
            direction=AlertDirection.BELOW,
            target_price=Decimal(105),
        )
        session.add_all([order, alert])
        session.commit()
        order_id, alert_id = order.id, alert.id

    codes: dict[str, int] = {}
    for step in _chain_steps():
        name, *rest = step
        if name == "metadata":  # Mondays only; this is a Wednesday.
            continue
        args = [a for a in rest if a != "$TICKERS"] + (["AAPL"] if "$TICKERS" in rest else [])
        codes[name] = cli.main([name, *args])

    # aegis-sync exits 2 when Aegis is not configured; the chain tolerates it.
    assert codes.pop("aegis-sync") == 2
    # revalidate-web exits 2 when WEB_REVALIDATE_URL is unset (RS-9); likewise.
    assert codes.pop("revalidate-web") == 2
    assert codes == dict.fromkeys(codes, 0), codes

    with Session(engine) as session:
        filled = session.get(PendingOrder, order_id)
        assert filled is not None and filled.status == OrderStatus.FILLED
        fired = session.get(Alert, alert_id)
        assert fired is not None and fired.triggered_at is not None
        snapshot_days = {s.date for s in session.exec(select(PortfolioSnapshot)).all()}
        assert WEDNESDAY.date() in snapshot_days
        runs = session.exec(select(JobRun)).all()
        skipped = {"aegis-sync", "revalidate-web"}
        assert {r.job for r in runs} == set(codes) | skipped
        statuses = {r.job: r.status for r in runs}
        assert all(statuses[job] == "skipped" for job in skipped)
        assert all(r.status == "succeeded" for r in runs if r.job not in skipped)
