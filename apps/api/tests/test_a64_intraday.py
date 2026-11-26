"""A6.4: intraday rules on setups, intraday strategy backtests and intraday
rule alerts (state per bar, dedupe per bar).

Synthetic minutes only (never the owner's files), on NSE sessions: IST = UTC
+ 5:30, so 09:15 IST is 03:45 UTC. The 60-minute bars of a regular NSE day
open at 09:15, 10:15, ..., 14:15 and 15:15 (the last one 15 minutes long).
"""

# pyright: reportAttributeAccessIssue=false, reportArgumentType=false

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from jose import jwt as jose_jwt
from sqlmodel import Session, select

from stockviz.models import Alert, AlertEvent, AlertKind, AlertRepeat, PriceBar, User
from stockviz.models.intraday import IntradayBar
from stockviz.services.alerts.intraday import evaluate_intraday_alerts, judge_bar
from stockviz.services.backtest.engine import _sharpe
from stockviz.services.backtest.strategy_run import periods_per_year
from stockviz.services.bars import intraday as intraday_mod
from stockviz.services.dsl import compile_rule, vector
from stockviz.services.dsl.data import load_symbol_intraday
from stockviz.services.instruments import resolve_symbol
from stockviz.services.setups import store
from stockviz.services.simulation import OrderSide, get_fee_schedule
from stockviz.settings import get_settings
from tests.symbols import seed_symbols

IST = timedelta(hours=5, minutes=30)
TICKER = "TCS.NS"
LATER = datetime(2026, 11, 26, 12, tzinfo=UTC)
D1, D2, D3 = date(2024, 11, 4), date(2024, 11, 5), date(2024, 11, 6)  # Mon-Wed, NSE sessions
SECRET = get_settings().internal_api_token


@pytest.fixture(autouse=True)
def _clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(intraday_mod, "now_utc", lambda: LATER)


def _utc(day: date, hhmm: str) -> datetime:
    h, m = (int(x) for x in hhmm.split(":"))
    return datetime.combine(day, time(h, m)) - IST


def _auth(user_id: int) -> dict[str, str]:
    return {"Authorization": f"Bearer {jose_jwt.encode({'sub': str(user_id)}, SECRET, 'HS256')}"}


def _user(session: Session) -> int:
    row = User(email="a64@stockviz.dev", name="A64")
    session.add(row)
    session.commit()
    assert row.id is not None
    return row.id


def _seed(session: Session, price: Callable[[date, datetime], float], days=(D1, D2, D3)) -> None:
    """Every minute of each NSE session; open = close = ``price(day, minute IST)``,
    so a 60m bar's open is its first minute's price."""
    seed_symbols(session, TICKER, currency="INR")
    instrument = resolve_symbol(session, TICKER)
    assert instrument is not None and instrument.id is not None
    for day in days:
        ts = _utc(day, "09:15")
        while ts < _utc(day, "15:30"):
            p = Decimal(str(price(day, ts + IST)))
            session.add(
                IntradayBar(instrument_id=instrument.id, feed="file", interval="1m", ts=ts,
                            open=p, high=p, low=p, close=p, volume=100, source="bulk_1m",
                            available_at=ts + timedelta(minutes=1))
            )  # fmt: skip
            ts += timedelta(minutes=1)
    session.commit()


def _step(changes: dict[tuple[date, str], float], base: float = 100.0):
    """A price that jumps to each value at its (day, HH:MM IST) and stays."""
    keys = sorted(changes)

    def price(day: date, local: datetime) -> float:
        value = base
        for k in keys:
            if (day, local.strftime("%H:%M")) >= k:
                value = changes[k]
        return value

    return price


def _run(client: TestClient, **over) -> dict:
    body = {
        "entry": {"rule": "close > 105"},
        "exit": {"rule": "close < 105"},
        "universe": {"ticker": TICKER},
        "from": D1.isoformat(),
        "to": D3.isoformat(),
        "initial_cash": "100000",
        "timeframe": "60m",
        "holdout": "none",
    }
    body.update(over)
    r = client.post("/v1/backtest/strategy", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def _bar(day: date, hhmm: str) -> str:
    return _utc(day, hhmm).isoformat()


# --- setups and the rule check ---------------------------------------------------


def test_rule_check_and_setup_versions_carry_the_timeframe(
    client: TestClient, session: Session
) -> None:
    r = client.post("/v1/rules/check", json={"rule": "close > daily.close", "timeframe": "5m"})
    assert r.json()["valid"] and r.json()["timeframe"] == "5m"
    assert "daily_bars" in r.json()["uses"]
    r = client.post("/v1/rules/check", json={"rule": "close > daily.close"})
    assert not r.json()["valid"] and "intraday" in r.json()["error"]["message"]
    r = client.post("/v1/rules/check", json={"rule": "rs(20) > 0", "timeframe": "15m"})
    assert "daily.rs" in r.json()["error"]["message"]

    uid = _user(session)
    r = client.post("/v1/setups", headers=_auth(uid),
                    json={"name": "Hourly", "kind": "alert", "rule": "close > 105",
                          "timeframe": "60m", "feed": "file"})  # fmt: skip
    assert r.status_code == 201, r.text
    setup = r.json()
    assert setup["latest_version"]["timeframe"] == "60m"
    assert setup["latest_version"]["feed"] == "file"
    # The same rule on daily bars is another version; the same rule on 60m is the same one.
    r = client.post(f"/v1/setups/{setup['id']}/versions", headers=_auth(uid),
                    json={"rule": "close > 105"})  # fmt: skip
    assert r.status_code == 201 and r.json()["timeframe"] == "daily"
    r = client.post(f"/v1/setups/{setup['id']}/versions", headers=_auth(uid),
                    json={"rule": "close  >  105", "timeframe": "60m", "feed": "file"})  # fmt: skip
    assert r.status_code == 200 and r.json()["version"] == 1
    r = client.post(f"/v1/setups/{setup['id']}/versions", headers=_auth(uid),
                    json={"rule": "close > 1", "feed": "file"})  # fmt: skip
    assert r.status_code == 422
    # Daily consumers refuse an intraday version.
    v1 = setup["latest_version"]["id"]
    r = client.get(f"/v1/screener?setup_version_id={v1}", headers=_auth(uid))
    assert r.status_code == 400 and "60m bars" in r.text


# --- the intraday backtester -----------------------------------------------------


def test_signal_on_bar_close_fills_the_next_bars_open(client: TestClient, session: Session) -> None:
    # 110 from 11:30 on D1, so the 11:15 bar closes at 110: fill at the 12:15 bar's open.
    _seed(session, _step({(D1, "11:30"): 110.0, (D1, "13:20"): 120.0, (D2, "11:00"): 100.0}))
    out = _run(client, fee_schedule="none")
    trade = out["trades"][0]
    assert trade["entry_at"] == _bar(D1, "12:15") and trade["entry_date"] == D1.isoformat()
    assert Decimal(trade["entry_price"]) == Decimal(110)
    # Exit: the 10:15 bar of D2 closes at 100, fill at the 11:15 bar's open (100).
    assert trade["exit_at"] == _bar(D2, "11:15") and trade["reason"] == "exit_rule"
    assert out["timeframe"] == "60m" and out["feed"] == "file" and out["feed_badge"]
    assert out["equity_curve"][0]["at"] == _bar(D1, "09:15")


def test_entries_never_fill_across_a_night(client: TestClient, session: Session) -> None:
    # Only the last bar (15:15-15:30) of D1 closes above 105: that signal is dropped.
    _seed(session, _step({(D1, "15:20"): 110.0, (D2, "09:15"): 104.0, (D2, "10:20"): 110.0}))
    out = _run(client, fee_schedule="none")
    assert out["skip_reasons"] == {"session_end": 1}
    assert out["trades"][0]["entry_at"] == _bar(D2, "11:15")


def test_exits_fill_across_a_night_and_same_day_costs(client: TestClient, session: Session) -> None:
    # Enter D1 12:15; the exit signal on D1's last bar fills at D2's open.
    _seed(session, _step({(D1, "11:30"): 110.0, (D1, "15:20"): 100.0, (D2, "09:15"): 101.0,
                          (D2, "10:30"): 110.0, (D2, "13:30"): 100.0}))  # fmt: skip
    out = _run(client)
    assert out["fee_schedule"] == "in_equity_delivery_nse"
    first, second = out["trades"][:2]
    assert first["exit_at"] == _bar(D2, "09:15") and Decimal(first["exit_price"]) == Decimal(101)
    assert first["same_day"] is False
    # Second trade: in at D2 11:15, out at D2 14:15 (the 13:15 bar closes at 100): same day.
    assert second["entry_at"] == _bar(D2, "11:15") and second["exit_at"] == _bar(D2, "14:15")
    assert second["same_day"] is True
    intraday = get_fee_schedule("in_equity_intraday_nse")
    delivery = get_fee_schedule("in_equity_delivery_nse")
    qty = Decimal(second["quantity"])
    leg = intraday.fees(OrderSide.BUY, qty, Decimal(110), on=D2).total
    assert Decimal(second["entry_fees"]) == leg
    assert (
        Decimal(second["exit_fees"])
        == intraday.fees(OrderSide.SELL, qty, Decimal(100), on=D2, dp_due=False).total
    )
    assert (
        Decimal(first["entry_fees"])
        == delivery.fees(OrderSide.BUY, Decimal(first["quantity"]), Decimal(110), on=D1).total
    )
    assert any("in_equity_intraday_nse" in n for n in out["notes"])


def test_flatten_at_close(client: TestClient, session: Session) -> None:
    _seed(session, _step({(D1, "11:30"): 110.0, (D1, "15:20"): 112.0}))
    out = _run(client, flatten_at_close=True, exit=None)
    trades = out["trades"]
    assert trades[0]["reason"] == "session_close"
    assert trades[0]["exit_at"] == _bar(D1, "15:15") and Decimal(trades[0]["exit_price"]) == 112
    assert trades[0]["same_day"] is True
    # Re-entered on D2 (close > 105 from its first bar) and flattened again.
    assert trades[1]["entry_at"] == _bar(D2, "10:15") and trades[1]["reason"] == "session_close"
    assert out["flatten_at_close"] is True
    held = [p for p in out["equity_curve"] if p["at"] == _bar(D1, "15:15")]
    assert held  # one point per bar


def test_annualisation_by_bars_a_year(client: TestClient, session: Session) -> None:
    _seed(session, _step({(D1, "11:30"): 110.0, (D1, "13:30"): 101.0, (D2, "10:30"): 108.0}))
    out = _run(client, fee_schedule="none")
    assert periods_per_year(TICKER, "60m") == 7 * 252
    assert periods_per_year(TICKER, "5m") == 75 * 252
    assert periods_per_year("AAPL", "15m") == 26 * 252
    assert out["periods_per_year"] == 7 * 252
    navs = [Decimal(p["nav"]) for p in out["equity_curve"]]
    assert out["summary"]["sharpe"] == pytest.approx(_sharpe(navs, periods_per_year=7 * 252))
    sharpe = out["report"]["sharpe"]
    assert sharpe["sharpe_annual"] == pytest.approx(sharpe["sharpe"] * (7 * 252) ** 0.5)


def test_adv_cap_reads_daily_volume_not_intraday(client: TestClient, session: Session) -> None:
    _seed(session, _step({(D1, "11:30"): 110.0}))
    out = _run(client, fee_schedule="none", adv_cap_pct=10, exit=None)
    assert out["liquidity"]["not_capped"] == 1  # no daily bars: not capped, counted
    # 20 daily bars before D1 at 110 x 1,000 shares: the cap is 10% of 110,000.
    for k in range(40):
        day = D1 - timedelta(days=k + 1)
        if day.weekday() < 5:
            session.add(PriceBar(ticker=TICKER, ts=datetime.combine(day, time.min), interval="1d",
                                 open=Decimal(110), high=Decimal(110), low=Decimal(110),
                                 close=Decimal(110), volume=1000, source="test"))  # fmt: skip
    session.commit()
    out = _run(client, fee_schedule="none", adv_cap_pct=10, exit=None)
    assert Decimal(out["trades"][0]["quantity"]) == 100  # 11,000 / 110


def test_a_daily_version_in_an_intraday_run_is_refused(
    client: TestClient, session: Session
) -> None:
    _seed(session, _step({}), days=(D1,))
    uid = _user(session)
    _setup, version = store.create_setup(session, uid, name="D", kind="strategy",
                                        rule=compile_rule("close > 1"))  # fmt: skip
    r = client.post("/v1/backtest/strategy", headers=_auth(uid), json={
        "entry": {"setup_version_id": version.id}, "universe": {"ticker": TICKER},
        "from": D1.isoformat(), "to": D1.isoformat(), "initial_cash": "1000",
        "timeframe": "60m"})  # fmt: skip
    assert r.status_code == 400 and "daily bars" in r.text
    r = client.post("/v1/backtest/strategy", json={
        "entry": {"rule": "close > 1"}, "universe": {"ticker": TICKER}, "from": "2024-01-01",
        "to": "2024-02-01", "initial_cash": "1000", "flatten_at_close": True})  # fmt: skip
    assert r.status_code == 400


# --- intraday rule alerts --------------------------------------------------------


def _alert(session: Session, rule: str, *, repeat=AlertRepeat.EVERY_CROSS, cooldown: int = 1,
           armed_at: datetime | None = None) -> Alert:  # fmt: skip
    uid = _user(session)
    _setup, version = store.create_setup(session, uid, name="Hourly", kind="alert",
                                         rule=compile_rule(rule, timeframe="60m"),
                                         timeframe="60m")  # fmt: skip
    alert = Alert(user_id=uid, ticker=TICKER, kind=AlertKind.RULE, setup_version_id=version.id,
                  params={"setup_name": "Hourly", "version": 1, "canonical": rule},
                  repeat=repeat, cooldown_sessions=cooldown,
                  armed_at=armed_at or _utc(D1, "09:00"))  # fmt: skip
    session.add(alert)
    session.commit()
    return alert


def _events(session: Session) -> list[AlertEvent]:
    return list(session.exec(select(AlertEvent).order_by(AlertEvent.id)).all())  # type: ignore[arg-type]


RULE = "close crosses_above 105"
PATH = {(D1, "11:30"): 110.0, (D1, "13:30"): 100.0, (D2, "10:30"): 110.0, (D2, "12:30"): 100.0,
        (D2, "13:30"): 110.0}  # fmt: skip


def test_alert_fires_per_bar_and_never_twice(session: Session) -> None:
    _seed(session, _step(PATH))
    alert = _alert(session, RULE)
    run = evaluate_intraday_alerts(session, since=_utc(D1, "09:15"), now=LATER)
    events = _events(session)
    assert [e.bar_at for e in events] == [_utc(D1, "11:15"), _utc(D2, "10:15"), _utc(D2, "13:15")]
    assert run.fired == 3 and run.bars == 3 * 7
    assert events[0].dedupe_key == f"{alert.id}:{_utc(D1, '11:15'):%Y-%m-%dT%H:%M}Z"
    assert events[0].feed == "file" and events[0].bar_date == D1
    assert "60m" in events[0].message and "12:15 IST" in events[0].message
    assert "File (local)" in events[0].message
    session.refresh(alert)
    assert alert.last_bar_at == _utc(D3, "15:15") and alert.last_fired_bar_at == _utc(D2, "13:15")
    assert alert.last_bar_date is None  # daily state untouched
    # A rerun over the same bars judges nothing and fires nothing.
    again = evaluate_intraday_alerts(session, since=_utc(D1, "09:15"), now=LATER)
    assert again.fired == 0 and again.bars == 0 and len(_events(session)) == 3
    # Even with the state wiped, the (alert, bar) key holds.
    alert.last_bar_at = None
    alert.last_state = None
    session.add(alert)
    session.commit()
    evaluate_intraday_alerts(session, since=_utc(D1, "09:15"), now=LATER)
    assert len(_events(session)) == 3


def test_alert_firings_equal_the_backtest_entry_signals(
    client: TestClient, session: Session
) -> None:
    _seed(session, _step(PATH))
    _alert(session, RULE)
    evaluate_intraday_alerts(session, since=_utc(D1, "09:15"), now=LATER)
    fired = [e.bar_at for e in _events(session)]
    data = load_symbol_intraday(session, TICKER, timeframe="60m", end=_utc(D3, "15:15"))
    signals = vector(compile_rule(RULE, timeframe="60m"), data)
    assert fired == [ts.to_pydatetime() for ts, v in signals.items() if v is not pd.NA and v]
    out = _run(client, entry={"rule": RULE}, exit={"rule": "close crosses_below 105"},
               fee_schedule="none")  # fmt: skip
    # Each firing's next bar is a backtest entry (the bar after the signal).
    entries = [t["entry_at"] for t in out["trades"]]
    nexts = [data.instants[data.instants.index(b) + 1].isoformat() for b in fired]
    assert entries == nexts


def test_closed_bars_only_and_arming(session: Session) -> None:
    _seed(session, _step(PATH), days=(D1,))
    # Armed at 12:30 IST: the 11:15 bar (closed 12:15) was already seen, so it arms only.
    alert = _alert(session, RULE, armed_at=_utc(D1, "12:30"))
    data = load_symbol_intraday(session, TICKER, timeframe="60m", end=_utc(D1, "15:15"))
    rule = compile_rule(RULE, timeframe="60m")
    # A bar not closed at "now" is not judged.
    assert judge_bar(session, alert, rule, data, _utc(D1, "11:15"), now=_utc(D1, "12:00")) is None
    judged = judge_bar(session, alert, rule, data, _utc(D1, "11:15"), now=LATER)
    assert judged is not None and judged.state is True and judged.fired is None
    assert judge_bar(session, alert, rule, data, _utc(D1, "11:15"), now=LATER) is None


def test_cooldown_counts_bars_of_the_timeframe(session: Session) -> None:
    _seed(session, _step(PATH))
    _alert(session, RULE, cooldown=20)  # 20 hourly bars: D2's crosses are inside it
    evaluate_intraday_alerts(session, since=_utc(D1, "09:15"), now=LATER)
    assert [e.bar_at for e in _events(session)] == [_utc(D1, "11:15")]


def test_once_and_the_nightly_job_skips_intraday_alerts(session: Session) -> None:
    from stockviz.services.alerts import evaluate_pending_alerts

    _seed(session, _step(PATH))
    alert = _alert(session, RULE, repeat=AlertRepeat.ONCE)
    assert evaluate_pending_alerts(session) == 0  # end-of-day pass leaves it alone
    session.refresh(alert)
    assert alert.last_bar_date is None and alert.last_state is None
    evaluate_intraday_alerts(session, since=_utc(D1, "09:15"), now=LATER)
    assert len(_events(session)) == 1


def test_cli_dry_run_writes_nothing(session: Session, engine, monkeypatch, capsys) -> None:
    from stockviz import cli

    monkeypatch.setattr(cli, "engine", engine)
    _seed(session, _step(PATH))
    _alert(session, RULE)
    assert cli.main(["evaluate-alerts", "--intraday", "--since", "2024-11-04T03:45",
                     "--dry-run"]) == 0  # fmt: skip
    assert "would fire 3" in capsys.readouterr().out
    assert _events(session) == []
    assert cli.main(["evaluate-alerts", "--intraday"]) == 1
