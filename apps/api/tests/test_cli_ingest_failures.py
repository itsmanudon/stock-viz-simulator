"""The nightly refresh steps report failure instead of success (audit MD-4)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlmodel import Session

from stockviz import cli
from stockviz.models import PriceBar, Symbol

TUESDAY_CRON = datetime(2025, 4, 8, 22, 0)  # 18:00 EDT: Tuesday 8 April is complete
TUESDAY = datetime(2025, 4, 8)
MONDAY = datetime(2025, 4, 7)


@pytest.fixture
def cli_env(engine, monkeypatch):
    monkeypatch.setattr(cli, "engine", engine)
    monkeypatch.setattr("stockviz._time.utcnow", lambda: TUESDAY_CRON)
    monkeypatch.setattr(cli, "get_settings", lambda: SimpleNamespace(alpha_vantage_key=""))
    with Session(engine) as session:
        for ticker in ("AAPL", "MSFT", "SHOP.TO"):
            session.add(Symbol(ticker=ticker, name=ticker))
        session.commit()
    return engine


def _fake_ingest(bar_dates: dict[str, datetime], raises: set[str] = frozenset()):  # type: ignore[assignment]
    def fake(session: Session, ticker: str, **_kw) -> int:
        if ticker in raises:
            raise RuntimeError("provider timeout")
        ts = bar_dates[ticker]
        session.add(
            PriceBar(
                ticker=ticker,
                ts=ts,
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
        return 1

    return fake


def test_one_failing_ticker_fails_the_run_but_not_the_others(cli_env, monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        cli,
        "ingest_ticker",
        _fake_ingest({"MSFT": TUESDAY, "SHOP.TO": TUESDAY}, raises={"AAPL"}),
    )

    assert cli.main(["ingest", "AAPL", "MSFT", "SHOP.TO"]) == 1
    captured = capsys.readouterr()
    # Tickers after the failure still ran.
    assert "MSFT: 1 (latest bar 2025-04-08)" in captured.out
    assert "SHOP.TO: 1" in captured.out
    assert "AAPL: FAILED (RuntimeError: provider timeout)" in captured.err


def test_a_run_where_nothing_reached_the_session_fails(cli_env, monkeypatch, capsys) -> None:
    """Every ticker stuck on Monday on Tuesday night: the refresh did not work."""
    monkeypatch.setattr(cli, "ingest_ticker", _fake_ingest({"AAPL": MONDAY, "MSFT": MONDAY}))

    assert cli.main(["ingest", "AAPL", "MSFT"]) == 1
    assert "no ticker reached the 2025-04-08 session" in capsys.readouterr().err


def test_one_ticker_behind_is_reported_not_failed(cli_env, monkeypatch, capsys) -> None:
    """Its market may have been closed: Toronto on a Canadian holiday."""
    monkeypatch.setattr(cli, "ingest_ticker", _fake_ingest({"AAPL": TUESDAY, "SHOP.TO": MONDAY}))

    assert cli.main(["ingest", "AAPL", "SHOP.TO"]) == 0
    assert "behind 2025-04-08: SHOP.TO" in capsys.readouterr().err


def test_fx_without_rates_fails(cli_env, monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "ingest_fx", lambda _s, ccy: 0 if ccy == "INR" else 5)
    assert cli.main(["fx", "EUR", "INR"]) == 1
    assert "no rates for INR" in capsys.readouterr().err

    monkeypatch.setattr(cli, "ingest_fx", lambda _s, _ccy: 5)
    assert cli.main(["fx", "EUR", "INR"]) == 0


def test_fx_error_fails_but_other_currencies_still_run(cli_env, monkeypatch, capsys) -> None:
    def fake(_session, ccy):
        if ccy == "EUR":
            raise ConnectionError("down")
        return 3

    monkeypatch.setattr(cli, "ingest_fx", fake)
    assert cli.main(["fx", "EUR", "GBP"]) == 1
    captured = capsys.readouterr()
    assert "GBP: 3" in captured.out
    assert "EUR: FAILED (ConnectionError: down)" in captured.err


def test_dividend_fetch_failure_is_reported(cli_env, monkeypatch, capsys) -> None:
    from stockviz.services.ingest import dividends

    def fetch(ticker: str):
        if ticker == "MSFT":
            raise TimeoutError("yfinance")
        return []

    monkeypatch.setattr(dividends, "_default_dividend_fetch", fetch)
    original = dividends.ingest_dividends_for_all

    def with_fake_fetch(session, *, only=None, failures=None):
        return original(session, fetch_fn=fetch, only=only, failures=failures)

    monkeypatch.setattr(cli, "ingest_dividends_for_all", with_fake_fetch)

    assert cli.main(["dividends"]) == 1
    assert "fetch failed for MSFT" in capsys.readouterr().err
