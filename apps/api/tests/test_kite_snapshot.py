"""Phase 4.7: optional Kite snapshots and the provider rank.

Kite is never called: responses are shaped like Kite Connect v3's documented
examples (session token, instruments CSV, day candles).
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime
from decimal import Decimal

import httpx
import pytest
from sqlmodel import Session, col, select

from stockviz.models import PriceBar
from stockviz.models.instrument import InstrumentIdentifier
from stockviz.services.ingest.bar_semantics import AdjustmentSemantics, SessionScope
from stockviz.services.ingest.history import snapshot
from stockviz.services.ingest.prices import (
    SOURCE_KITE,
    SOURCE_YFINANCE,
    BarRecord,
    upsert_bars,
)
from stockviz.services.ingest.providers import kite
from tests.pg_scratch import postgres_admin_url, scratch_postgres_engine
from tests.symbols import seed_symbols

INSTRUMENTS_CSV = (
    "instrument_token,exchange_token,tradingsymbol,name,last_price,expiry,strike,"
    "tick_size,lot_size,instrument_type,segment,exchange\n"
    "738561,2885,RELIANCE,RELIANCE INDUSTRIES,0,,0,0.05,1,EQ,NSE,NSE\n"
    "256265,1001,NIFTY 50,NIFTY 50,0,,0,0,0,EQ,INDICES,NSE\n"
)


def _candles(*days: tuple[str, float]) -> dict:
    return {
        "status": "success",
        "data": {"candles": [[f"{d}T00:00:00+0530", c, c + 5, c - 5, c, 1000] for d, c in days]},
    }


class FakeKite:
    def __init__(self, candles: dict) -> None:
        self.candles = candles
        self.history_calls: list[dict[str, str]] = []
        self.posted: dict[str, str] = {}

    def post(self, url: str, data: dict[str, str], headers: dict[str, str]) -> httpx.Response:
        self.posted = data
        return httpx.Response(200, json={"status": "success", "data": {"access_token": "AT"}})

    def get(self, url: str, params: dict[str, str], headers: dict[str, str]) -> httpx.Response:
        assert headers["Authorization"] == "token KEY:AT"
        if url.endswith("/instruments/NSE"):
            return httpx.Response(200, text=INSTRUMENTS_CSV)
        self.history_calls.append(params)
        return httpx.Response(200, json=self.candles)


def _client(fake: FakeKite) -> kite.KiteClient:
    return kite.open_session("KEY", "SECRET", "REQ", post=fake.post, get=fake.get)


def test_session_uses_the_documented_checksum() -> None:
    fake = FakeKite(_candles())
    client = _client(fake)
    assert client.access_token == "AT"
    assert fake.posted["checksum"] == hashlib.sha256(b"KEYREQSECRET").hexdigest()
    assert kite.login_url("KEY") == "https://kite.zerodha.com/connect/login?v=3&api_key=KEY"


def test_candles_become_venue_dated_kite_bars_in_2000_day_requests() -> None:
    fake = FakeKite(_candles(("2026-11-10", 1500.0)))
    client = _client(fake)
    assert client.instrument_tokens("NSE") == {"RELIANCE": 738561}

    bars = client.daily_bars("RELIANCE.NS", 738561, start=date(2015, 1, 1), end=date(2026, 11, 12))
    assert len(fake.history_calls) == 3  # 4,334 days in 2000-day pieces
    assert fake.history_calls[0] == {"from": "2015-01-01", "to": "2020-06-22"}
    bar = bars[0]
    assert (bar.ts, bar.close, bar.source) == (datetime(2026, 11, 10), Decimal("1500.0"), "kite")
    assert kite.kite_symbol("RELIANCE.NS") == ("NSE", "RELIANCE")
    assert kite.kite_symbol("AAPL") is None


def test_a_kite_error_body_names_the_error_not_the_token() -> None:
    with pytest.raises(kite.KiteError, match="TokenException: Token is invalid"):
        kite._json(
            httpx.Response(
                403,
                json={
                    "status": "error",
                    "error_type": "TokenException",
                    "message": "Token is invalid",
                },
            )
        )


def _bar(source: str, close: str, day: int = 10) -> BarRecord:
    value = Decimal(close)
    return BarRecord(
        ticker="RELIANCE.NS",
        ts=datetime(2026, 11, day),
        interval="1d",
        open=value,
        high=value,
        low=value,
        close=value,
        volume=Decimal(1),
        source=source,
        adjustment_semantics=AdjustmentSemantics.SPLIT_ADJUSTED,
        session_scope=SessionScope.REGULAR,
    )


def _closes(session: Session) -> list[tuple[Decimal, str | None]]:
    rows = session.exec(select(PriceBar).order_by(col(PriceBar.ts))).all()
    return [(r.close, r.source) for r in rows]


def test_dry_run_reports_and_writes_nothing(session: Session) -> None:
    seed_symbols(session, "RELIANCE.NS", currency="INR")
    upsert_bars(session, [_bar(SOURCE_YFINANCE, "1490", day=10)])
    session.commit()

    def fetch(ticker: str):
        return [_bar(SOURCE_KITE, "1500", day=10), _bar(SOURCE_KITE, "1510", day=11)], "738561"

    (report,) = snapshot(session, ["RELIANCE.NS"], fetch, scheme="kite", apply=False)
    assert (report.fetched, report.new_days, report.overlap) == (2, 1, 1)
    assert report.max_close_diff_pct == Decimal("0.67")
    assert _closes(session) == [(Decimal("1490.000000"), "yfinance")]


def test_apply_writes_kite_bars_and_yfinance_cannot_replace_them(session: Session) -> None:
    seed_symbols(session, "RELIANCE.NS", currency="INR")
    upsert_bars(session, [_bar(SOURCE_YFINANCE, "1490")])
    session.commit()

    snapshot(
        session,
        ["RELIANCE.NS"],
        lambda _t: ([_bar(SOURCE_KITE, "1500")], "738561"),
        scheme="kite",
        apply=True,
    )
    upsert_bars(session, [_bar(SOURCE_YFINANCE, "1490"), _bar(SOURCE_YFINANCE, "1520", day=11)])
    session.commit()

    assert _closes(session) == [
        (Decimal("1500.000000"), "kite"),  # kept: outranks yfinance
        (Decimal("1520.000000"), "yfinance"),  # a newer day is still added
    ]
    ident = session.exec(
        select(InstrumentIdentifier).where(col(InstrumentIdentifier.scheme) == "kite")
    ).one()
    assert ident.value == "738561"


def test_a_failed_ticker_is_reported_and_the_rest_still_run(session: Session) -> None:
    seed_symbols(session, "RELIANCE.NS", "TCS.NS", currency="INR")

    def fetch(ticker: str):
        if ticker == "TCS.NS":
            raise ValueError("NSE:TCS not in Kite's instrument list")
        return [_bar(SOURCE_KITE, "1500")], None

    reports = snapshot(session, ["TCS.NS", "RELIANCE.NS"], fetch, scheme="kite", apply=True)
    assert reports[0].error and "TCS" in reports[0].error
    assert reports[1].written == 1


def test_without_keys_the_commands_are_off(monkeypatch, capsys) -> None:
    from stockviz import cli

    monkeypatch.delenv("KITE_API_KEY", raising=False)
    monkeypatch.delenv("KITE_API_SECRET", raising=False)
    cli.get_settings.cache_clear()
    assert cli.main(["kite-login-url"]) == 2
    assert cli.main(["ingest-history", "--provider", "kite", "--request-token", "x"]) == 2
    assert cli.main(["ingest-history", "--provider", "truedata"]) == 2
    assert "Kite is off" in capsys.readouterr().out


@pytest.mark.skipif(postgres_admin_url() is None, reason="DATABASE_URL is not PostgreSQL")
def test_postgres_upsert_keeps_the_higher_ranked_source() -> None:
    with scratch_postgres_engine() as engine, Session(engine) as session:
        seed_symbols(session, "RELIANCE.NS", currency="INR")
        upsert_bars(session, [_bar(SOURCE_KITE, "1500")])
        upsert_bars(session, [_bar(SOURCE_YFINANCE, "1490")])
        session.commit()
        assert _closes(session) == [(Decimal("1500.000000"), "kite")]
        upsert_bars(session, [_bar(SOURCE_KITE, "1505")])
        session.commit()
        assert _closes(session) == [(Decimal("1505.000000"), "kite")]
