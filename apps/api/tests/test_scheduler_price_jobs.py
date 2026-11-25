"""The scheduler's price jobs keep Kafka off the default path (A0)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlmodel import Session, select

from stockviz import scheduler
from stockviz.models import OutboxEvent
from tests.symbols import seed_symbols


@pytest.fixture
def jobs(engine, monkeypatch):
    monkeypatch.setattr(scheduler, "engine", engine)
    calls: dict[str, list[str]] = {"ingest": [], "metrics": [], "alerts": []}

    def fake_ingest(session, ticker, **_kw):
        if ticker == "BAD":
            raise RuntimeError("provider timeout")
        calls["ingest"].append(ticker)
        return 1

    monkeypatch.setattr(scheduler, "ingest_ticker", fake_ingest)
    monkeypatch.setattr(
        scheduler,
        "refresh_symbol_metrics",
        lambda session, tickers, commit: calls["metrics"].extend(tickers),
    )
    monkeypatch.setattr(
        scheduler,
        "evaluate_pending_alerts",
        lambda session, ticker, commit: calls["alerts"].append(ticker),
    )
    with Session(engine) as session:
        seed_symbols(session, "AAPL", "MSFT", "BAD")
    return calls


def _settings(monkeypatch, outbox: bool) -> None:
    monkeypatch.setattr(
        scheduler,
        "get_settings",
        lambda: SimpleNamespace(events_outbox_enabled=outbox, alpha_vantage_key=""),
    )


def _outbox(engine) -> list[OutboxEvent]:
    with Session(engine) as session:
        return list(session.exec(select(OutboxEvent)).all())


def test_by_default_prices_refresh_in_process_with_alerts(jobs, engine, monkeypatch) -> None:
    _settings(monkeypatch, outbox=False)
    scheduler.daily_price_refresh()
    assert jobs["ingest"] == ["AAPL", "MSFT"]  # BAD failed and did not stop the rest
    assert jobs["metrics"] == ["AAPL", "MSFT"]
    assert jobs["alerts"] == ["AAPL", "MSFT"]
    assert _outbox(engine) == []


def test_the_events_lab_enqueues_for_kafka_instead(jobs, engine, monkeypatch) -> None:
    _settings(monkeypatch, outbox=True)
    scheduler.daily_price_refresh()
    assert jobs["ingest"] == []
    assert len(_outbox(engine)) == 3


def test_the_hourly_job_takes_the_same_path(jobs, engine, monkeypatch) -> None:
    _settings(monkeypatch, outbox=False)
    monkeypatch.setattr(scheduler, "TOP_TICKERS_HOURLY", ("AAPL",))
    scheduler.hourly_top_movers()
    assert jobs["ingest"] == ["AAPL"]
    assert _outbox(engine) == []


def test_the_default_is_off() -> None:
    from stockviz.settings import Settings

    assert Settings.model_fields["events_outbox_enabled"].default is False
