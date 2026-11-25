"""A4.2 (M7.2): date-versioned fee schedules, Indian intraday and F&O rates,
default-on costs for Indian symbols, net first, and the ADV cap.

Rates and sources: ``services/simulation/fees.py`` and the workspace note
``docs/a4-cost-sources.md`` (every figure read 26 Nov 2026).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from itertools import pairwise

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from stockviz.models import ExperimentRun, FxRate, PriceBar, Trade
from stockviz.services.backtest.engine import run_backtest
from stockviz.services.backtest.fills import book
from stockviz.services.backtest.registry import result_differences
from stockviz.services.backtest.strategy import Sizing, Stops, SymbolInput, run_strategy
from stockviz.services.simulation import (
    LEGACY_CLOSE,
    NEXT_OPEN,
    MarketSnapshot,
    OrderIntent,
    OrderSide,
    SimLedger,
    SimulationOrderType,
    get_fee_schedule,
)
from stockviz.services.simulation.fees import (
    FAMILIES,
    NSE_STT_2024,
    NSE_STT_2026,
)
from tests.symbols import seed_symbols
from tests.test_strategy_backtest import body, headers, seed_walk, user

D = Decimal
BUY, SELL = OrderSide.BUY, OrderSide.SELL


def parts(name: str, side: OrderSide, qty, price, on: date, **kw) -> dict[str, Decimal]:
    return dict(get_fee_schedule(name).fees(side, D(qty), D(price), on=on, **kw).components)


# --- version selection --------------------------------------------------------


@pytest.mark.parametrize(
    ("on", "starts"),
    [
        (date(2024, 10, 1), date(2024, 10, 1)),
        (date(2026, 2, 28), date(2024, 10, 1)),
        (date(2026, 3, 1), date(2026, 3, 1)),
        (date(2026, 3, 31), date(2026, 3, 1)),
        (date(2026, 4, 1), date(2026, 4, 1)),
        (date(2030, 1, 1), date(2026, 4, 1)),
    ],
)
def test_version_boundaries_are_inclusive(on: date, starts: date) -> None:
    version, before = get_fee_schedule("in_futures_nse").version_on(on)
    assert version is not None and version.effective_from == starts and not before


def test_before_coverage_uses_the_earliest_version_and_says_so() -> None:
    nse = get_fee_schedule("in_equity_delivery_nse")
    assert nse.coverage_from == date(2024, 10, 1)
    fees = nse.fees(BUY, D(10), D(100), on=date(2019, 6, 3))
    assert fees.before_coverage and fees.version is not None
    assert fees.version.effective_from == date(2024, 10, 1)
    assert not nse.fees(BUY, D(10), D(100), on=date(2025, 1, 2)).before_coverage


def test_versions_do_not_overlap_or_leave_gaps() -> None:
    for family in FAMILIES:
        ordered = sorted(family.versions, key=lambda v: v.effective_from)
        for a, b in pairwise(ordered):
            assert a.effective_to is not None, family.name
            assert b.effective_from == a.effective_to + timedelta(days=1), family.name
        if ordered:
            assert ordered[-1].effective_to is None, family.name
        for v in ordered:
            for c in v.components:
                assert c.source.url.startswith("https://") and c.source.title, (family.name, c.key)


def test_old_names_map_to_the_versioned_families() -> None:
    assert get_fee_schedule("in_delivery_nse_2026") is get_fee_schedule("in_equity_delivery_nse")
    assert get_fee_schedule("in_delivery_bse_2026") is get_fee_schedule("in_equity_delivery_bse")
    assert get_fee_schedule("us_equity_2026") is get_fee_schedule("us_equity")


# --- the acceptance: F&O across 1 Apr 2026 -------------------------------------


def test_fno_series_across_1_april_2026_applies_old_then_new_stt_with_sources() -> None:
    """A synthetic futures and options fill series spanning the Finance Act
    2026 change: STT 0.02% / 0.10% (NSE/FATAX/63809) up to 31 Mar 2026 and
    0.05% / 0.15% (NSE/FATAX/73524) from 1 Apr 2026, each fill citing it."""
    days = [
        date(2026, 3, 27),
        date(2026, 3, 30),
        date(2026, 3, 31),
        date(2026, 4, 1),
        date(2026, 4, 2),
    ]
    fut = get_fee_schedule("in_futures_nse")
    opt = get_fee_schedule("in_options_nse")
    for day in days:
        after = day >= date(2026, 4, 1)
        f = fut.fees(SELL, D(75), D(24000), on=day)  # one NIFTY lot at 24,000
        stt = next(line for line in f.lines if line.key == "stt")
        assert stt.amount == (D(900) if after else D(360))  # 0.05% / 0.02% of 18,00,000
        assert stt.component is not None
        assert stt.component.source is (NSE_STT_2026 if after else NSE_STT_2024)
        o = opt.fees(SELL, D(75), D(120), on=day)  # premium 120 x 75 = 9,000
        ostt = next(line for line in o.lines if line.key == "stt")
        assert ostt.amount == (D(14) if after else D(9))  # 0.15% = 13.5 -> 14; 0.10% = 9
        assert ostt.component is not None
        assert ostt.component.source is (NSE_STT_2026 if after else NSE_STT_2024)
        for line in (*f.lines, *o.lines):
            if line.component is not None:
                assert line.component.source.url and line.component.source.date
        # Buys pay no STT in either period.
        assert "stt" not in dict(fut.fees(BUY, D(75), D(24000), on=day).components)


def test_nse_ipft_folded_into_the_charge_from_1_march_2026() -> None:
    before = parts("in_futures_nse", BUY, 75, 24000, date(2026, 2, 27))
    after = parts("in_futures_nse", BUY, 75, 24000, date(2026, 3, 2))
    assert before["exchange_transaction"] == D("31.14")  # 0.00173% of 18,00,000
    assert before["ipft"] == D("1.80")  # Rs 10 per crore
    assert "ipft" not in after and after["exchange_transaction"] == D("32.94")  # 0.00183%


# --- worked examples: Zerodha's brokerage calculator --------------------------
# The calculator's default outputs (zerodha.com/brokerage-calculator, read
# 26 Nov 2026) fit buy value 4,00,000 and sell value 4,40,000 (options 40,000
# and 44,000). It sums each component over both legs; StockViz prices each
# fill and rounds per fill, so a component can differ by a paisa, and the
# calculator rounds stamp duty to the rupee (options: 1 where 0.003% of
# 40,000 is 1.20).

NOW = date(2026, 11, 26)


def _legs(name: str, buy_value: int, sell_value: int, qty: int = 100) -> dict[str, Decimal]:
    out: dict[str, Decimal] = {}
    for side, value in ((BUY, buy_value), (SELL, sell_value)):
        for k, v in parts(name, side, qty, D(value) / qty, NOW).items():
            out[k] = out.get(k, D(0)) + v
    return out


def test_zerodha_calculator_delivery() -> None:
    got = _legs("in_equity_delivery_nse", 400_000, 440_000)
    assert got["stt"] == 840
    assert got["exchange_transaction"] == D("25.79")
    assert got["gst"] == D("4.79")
    assert got["sebi"] == D("0.84")
    assert got["stamp_duty"] == 60
    # The calculator's total 931.42 has no DP charge (it is per scrip per day
    # on the depository side); StockViz adds it to the sell.
    assert got["dp_charge"] == D("15.34")
    assert sum(got.values()) - got["dp_charge"] == D("931.42")


def test_zerodha_calculator_intraday() -> None:
    got = _legs("in_equity_intraday_nse", 400_000, 440_000)
    assert got == {
        "brokerage": D(40),  # Rs 20 a leg: 0.03% would be more
        "stt": D(110),  # 0.025% of the sell
        "exchange_transaction": D("25.79"),
        "sebi": D("0.84"),
        "gst": D("11.99"),
        "stamp_duty": D(12),  # 0.003% of the buy
    }
    assert sum(got.values()) == D("200.62")


def test_zerodha_calculator_futures() -> None:
    got = _legs("in_futures_nse", 400_000, 440_000)
    assert got == {
        "brokerage": D(40),
        "stt": D(220),  # 0.05% of the sell (from 1 Apr 2026)
        "exchange_transaction": D("15.37"),
        "sebi": D("0.84"),
        "gst": D("10.12"),
        "stamp_duty": D(8),
    }
    assert sum(got.values()) == D("294.33")


def test_zerodha_calculator_options() -> None:
    got = _legs("in_options_nse", 40_000, 44_000)
    assert got["brokerage"] == 40  # flat Rs 20 an order
    assert got["stt"] == 66  # 0.15% of the sell premium
    assert got["sebi"] == D("0.08")
    assert got["gst"] == D("12.59")
    # Per-fill rounding: 14.21 + 15.63 against the calculator's 29.85.
    assert got["exchange_transaction"] == D("29.84")
    assert got["stamp_duty"] == D("1.20")  # the calculator shows 1


# --- component rules ------------------------------------------------------------


def test_gst_base_is_brokerage_exchange_sebi_and_ipft_only() -> None:
    p = parts("in_equity_intraday_nse", BUY, 100, 1000, date(2025, 6, 2))  # 1,00,000
    base = p["brokerage"] + p["exchange_transaction"] + p["sebi"] + p["ipft"]
    assert p["brokerage"] == D(20)  # 0.03% = 30 > 20
    assert p["gst"] == (base * D("0.18")).quantize(D("0.01"))
    # STT and stamp duty are not in the GST base.
    assert p["gst"] < (base + p["stamp_duty"]) * D("0.18")


def test_stamp_duty_is_buy_only_and_stt_follows_each_segments_side() -> None:
    day = date(2026, 5, 4)
    for name in (
        "in_equity_delivery_nse",
        "in_equity_intraday_nse",
        "in_futures_nse",
        "in_options_nse",
    ):
        assert "stamp_duty" in parts(name, BUY, 10, 100, day)
        assert "stamp_duty" not in parts(name, SELL, 10, 100, day)
    assert "stt" in parts("in_equity_delivery_nse", BUY, 10, 100, day)  # both sides
    assert "stt" in parts("in_equity_delivery_nse", SELL, 10, 100, day)
    for name in ("in_equity_intraday_nse", "in_futures_nse", "in_options_nse"):
        assert "stt" not in parts(name, BUY, 100, 100, day), name  # sell side only
        assert "stt" in parts(name, SELL, 100, 100, day), name


def test_zero_brokerage_model() -> None:
    p = parts("in_futures_nse", BUY, 75, 24000, NOW, brokerage="zero")
    assert "brokerage" not in p and "gst" in p


def test_dp_charge_once_per_scrip_per_day_through_book() -> None:
    ledger = SimLedger(cash=D(1_000_000))
    nse = get_fee_schedule("in_equity_delivery_nse")
    seen: set = set()
    day1 = datetime(2026, 5, 4, tzinfo=None)

    def fill(side: OrderSide, ticker: str, day: datetime):
        order = OrderIntent(ticker=ticker, side=side, order_type=SimulationOrderType.MARKET,
                            quantity=D(10), submitted_at=day)  # fmt: skip
        bar = MarketSnapshot(ticker=ticker, observed_at=day, interval="1d", open=D(100),
                             high=D(100), low=D(100), close=D(100), volume=D(1))  # fmt: skip
        out = book(ledger, order, bar, LEGACY_CLOSE, schedule=nse, dp_seen=seen)
        assert out is not None
        return dict(out.fees.components)

    from datetime import UTC

    d1 = day1.replace(tzinfo=UTC)
    fill(BUY, "TCS.NS", d1)
    fill(BUY, "TCS.NS", d1)
    fill(BUY, "INFY.NS", d1)
    assert "dp_charge" in fill(SELL, "TCS.NS", d1)
    assert "dp_charge" not in fill(SELL, "TCS.NS", d1)  # same scrip, same day
    assert "dp_charge" in fill(SELL, "INFY.NS", d1)  # another scrip
    fill(BUY, "TCS.NS", d1 + timedelta(days=1))
    assert "dp_charge" in fill(SELL, "TCS.NS", d1 + timedelta(days=1))  # next day


def test_us_sec_fee_follows_its_dates() -> None:
    us = get_fee_schedule("us_equity")
    value = (D(1000), D(100))  # $100,000 of sales
    assert parts("us_equity", SELL, *value, date(2025, 3, 3))["sec_section_31"] == D("2.78")
    assert "sec_section_31" not in parts("us_equity", SELL, *value, date(2025, 6, 2))  # $0.00
    assert parts("us_equity", SELL, *value, date(2026, 4, 6))["sec_section_31"] == D("2.06")
    assert parts("us_equity", SELL, *value, date(2025, 6, 2))["finra_taf"] == D("0.17")
    assert parts("us_equity", SELL, *value, date(2026, 6, 1))["finra_taf"] == D("0.20")
    assert "finra_taf" not in parts("us_equity", SELL, *value, date(2026, 11, 2))  # paused
    early = us.fees(SELL, *value, on=date(2025, 3, 3))
    assert early.before_coverage  # start of the $27.80 period not confirmed
    assert not us.fees(BUY, *value, on=date(2025, 3, 3)).components


# --- the schedules listing and the order review's estimate ----------------------


def test_schedules_listing(client: TestClient) -> None:
    out = client.get("/v1/fees/schedules").json()
    names = {s["name"] for s in out["schedules"]}
    assert {"in_futures_nse", "in_options_nse", "in_equity_intraday_nse", "us_equity"} <= names
    assert out["defaults"] == {"XNSE": "in_equity_delivery_nse", "XBOM": "in_equity_delivery_bse"}
    fut = next(s for s in out["schedules"] if s["name"] == "in_futures_nse")
    assert [v["effective_from"] for v in fut["versions"]] == [
        "2024-10-01",
        "2026-03-01",
        "2026-04-01",
    ]
    stt = next(c for c in fut["versions"][-1]["components"] if c["key"] == "stt")
    assert stt["rate_text"] == "0.05% of value" and stt["side"] == "sell"
    assert stt["source"]["url"].endswith("FATAX73524.pdf")
    assert stt["source"]["date"] == "2026-03-31" and stt["source"]["read_on"] == "2026-11-26"
    nse = next(s for s in out["schedules"] if s["name"] == "in_equity_delivery_nse")
    assert nse["aliases"] == ["in_delivery_nse_2026"] and nse["default_for"] == ["XNSE"]


def _bar(session: Session, ticker: str, day: datetime, close: str, volume: int = 1000) -> None:
    price = D(close)
    session.add(PriceBar(ticker=ticker, ts=day, interval="1d", open=price, high=price, low=price,
                         close=price, volume=volume, source="test"))  # fmt: skip


def test_fee_estimate_for_the_order_review(client: TestClient, session: Session) -> None:
    seed_symbols(session, "TCS.NS", currency="INR")
    seed_symbols(session, "AAPL")
    _bar(session, "TCS.NS", datetime(2026, 5, 4), "2500")
    _bar(session, "AAPL", datetime(2026, 5, 4), "200")
    session.commit()
    res = client.get("/v1/fees/estimate", params={"ticker": "TCS.NS", "side": "buy",
                                                   "quantity": "100", "on": "2026-05-04"})  # fmt: skip
    out = res.json()
    assert res.status_code == 200, out
    assert out["schedule"] == "in_equity_delivery_nse" and out["effective_from"] == "2026-03-01"
    keys = [line["key"] for line in out["lines"]]
    assert keys == ["stt", "exchange_transaction", "sebi", "gst", "stamp_duty"]
    assert D(out["net_amount"]) == D(out["notional"]) + D(out["total"])
    assert all(line["source"]["url"] for line in out["lines"])
    sell = client.get("/v1/fees/estimate", params={"ticker": "TCS.NS", "side": "sell",
                                                   "quantity": "100"}).json()  # fmt: skip
    assert sell["dp_note"] and D(sell["net_amount"]) == D(sell["notional"]) - D(sell["total"])
    us = client.get("/v1/fees/estimate", params={"ticker": "AAPL", "side": "sell",
                                                 "quantity": "10"}).json()  # fmt: skip
    assert us["schedule"] == "none" and us["lines"] == [] and D(us["total"]) == 0
    assert client.get("/v1/fees/estimate", params={"ticker": "NOPE", "side": "buy",
                                                   "quantity": "1"}).status_code == 404  # fmt: skip


# --- default on: live paper fills ----------------------------------------------


def _inr_market(session: Session) -> None:
    seed_symbols(session, "TCS.NS", currency="INR")
    today = datetime.now()
    _bar(session, "TCS.NS", datetime(today.year, today.month, today.day), "2500")
    for day in {today.date(), today.date() - timedelta(days=1)}:
        session.add(FxRate(currency="INR", date=day, usd_rate=D("0.012")))
    session.commit()


def test_live_indian_fills_pay_the_nse_schedule(client: TestClient, session: Session) -> None:
    _inr_market(session)
    uid = user(session, "a42-live@stockviz.dev")
    h = headers(uid)
    before = D(client.get("/v1/portfolio", headers=h).json()["cash_balance"])
    res = client.post("/v1/trades", json={"ticker": "TCS.NS", "side": "buy", "quantity": "10"},
                      headers=h)  # fmt: skip
    assert res.status_code == 201, res.text
    buy = res.json()
    fees = D(buy["fees"])
    assert fees > 0 and buy["fee_schedule"] == "in_equity_delivery_nse"
    assert D(buy["net_native"]) == D(buy["total_native"]) + fees
    assert {line["key"] for line in buy["fee_lines"]} == {
        "stt", "exchange_transaction", "sebi", "gst", "stamp_duty"
    }  # fmt: skip
    after = D(client.get("/v1/portfolio", headers=h).json()["cash_balance"])
    # A USD account converts value + fees from dollars at 0.012.
    assert before - after == ((D(25000) + fees) * D("0.012")).quantize(D("0.000001"))

    sells = []
    for _ in range(2):
        r = client.post("/v1/trades", json={"ticker": "TCS.NS", "side": "sell", "quantity": "5"},
                        headers=h)  # fmt: skip
        assert r.status_code == 201, r.text
        sells.append(r.json())
    keys = [{line["key"] for line in s["fee_lines"]} for s in sells]
    assert "dp_charge" in keys[0] and "dp_charge" not in keys[1]  # once per scrip per day
    assert D(sells[0]["net_native"]) == D(sells[0]["total_native"]) - D(sells[0]["fees"])
    assert D(sells[0]["realized_pnl_net"]) < D(sells[0]["realized_pnl"])

    p = client.get("/v1/portfolio", headers=h).json()
    paid = sum(D(t["fees"]) for t in (buy, *sells))
    assert D(p["fees_paid"]) == (paid * D("0.012")).quantize(D("0.000001"))
    assert D(p["realized_pl_net"]) == D(p["realized_pl"]) - D(p["fees_paid"])


def test_pending_indian_buy_reserves_its_fees(client: TestClient, session: Session) -> None:
    _inr_market(session)
    uid = user(session, "a42-pending@stockviz.dev")
    h = headers(uid)
    res = client.post("/v1/orders", json={"ticker": "TCS.NS", "side": "buy", "order_type": "limit",
                                           "quantity": "10", "limit_price": "2400"},
                      headers=h)  # fmt: skip
    assert res.status_code == 201, res.text
    from stockviz.services.trading.buying_power import buy_reservation

    reserved = buy_reservation(session, ticker="TCS.NS", quantity=D(10), limit_price=D(2400))
    assert reserved > (D(24000) * D("0.012"))


def test_us_live_fills_stay_fee_free(client: TestClient, session: Session) -> None:
    seed_symbols(session, "AAPL")
    today = datetime.now()
    _bar(session, "AAPL", datetime(today.year, today.month, today.day), "200")
    session.commit()
    uid = user(session, "a42-us@stockviz.dev")
    r = client.post("/v1/trades", json={"ticker": "AAPL", "side": "buy", "quantity": "3"},
                    headers=headers(uid))  # fmt: skip
    assert r.status_code == 201, r.text
    assert D(r.json()["fees"]) == 0 and r.json()["fee_schedule"] == "none"


def test_old_trades_are_not_recalculated(client: TestClient, session: Session) -> None:
    _inr_market(session)
    uid = user(session, "a42-old@stockviz.dev")
    h = headers(uid)
    client.post("/v1/trades", json={"ticker": "TCS.NS", "side": "buy", "quantity": "1"}, headers=h)
    trade = session.exec(select(Trade)).one()
    trade.fees, trade.fee_schedule, trade.fee_lines = None, None, None  # as before A4.2
    session.add(trade)
    session.commit()
    listed = client.get("/v1/trades", headers=h).json()
    rows = listed if isinstance(listed, list) else listed["items"]
    assert rows[0]["fees"] is None and rows[0]["net_native"] is None


# --- backtests: default on, net first, the costs disclosure --------------------


def auto_body(**over) -> dict:
    out = body(**over)
    out.pop("fee_schedule")
    return out


def test_indian_backtest_defaults_to_nse_costs_net_first(
    client: TestClient, session: Session
) -> None:
    seed_walk(session, "TCS.NS", seed=3, currency="INR")
    out = client.post("/v1/backtest/strategy", json=auto_body(universe={"ticker": "TCS.NS"})).json()
    assert out["fee_schedule"] == "in_equity_delivery_nse"
    s = out["summary"]
    assert D(s["total_fees"]) > 0 and s["gross_return"] > s["total_return"]
    costs = out["costs"]
    assert costs["schedule"] == "in_equity_delivery_nse" and costs["requested"] == "auto"
    assert costs["price_bands_checked"] is False and "not checked" in costs["price_bands_note"]
    assert sum(v["fills"] for v in costs["versions"]) > 0
    # The walk is in 2023-24: before the earliest confirmed date, and said so.
    assert costs["fills_before_coverage"] == sum(v["fills"] for v in costs["versions"])
    for v in costs["versions"]:
        assert all(c["source"]["url"] for c in v["components"])


def test_us_backtest_default_is_none_and_template_net_first(
    client: TestClient, session: Session
) -> None:
    seed_walk(session, "AAPL", seed=1)
    out = client.post("/v1/backtest/strategy", json=auto_body()).json()
    assert out["fee_schedule"] == "none" and out["costs"]["price_bands_note"] is None
    tpl = client.post("/v1/backtest", json={
        "ticker": "AAPL", "from": "2023-06-01", "to": "2024-02-28", "initial_cash": "100000",
        "strategy": {"type": "sma_crossover", "short_window": 5, "long_window": 20},
        "spread_bps": 10,
    }).json()  # fmt: skip
    s = tpl["summary"]
    assert tpl["fee_schedule"] == "none"
    assert s["gross_return"] >= s["total_return"] and D(s["price_costs"]) > 0
    assert tpl["liquidity"]["adv_cap_pct"] == 10


# --- the ADV cap ----------------------------------------------------------------


def _symbol(n: int, volume: int, *, entry_at: int) -> SymbolInput:
    days = [date(2025, 1, 1) + timedelta(days=i) for i in range(n)]
    px = [D(100)] * n
    return SymbolInput(
        ticker="X", dates=days,
        ts=[datetime(d.year, d.month, d.day).astimezone() for d in days],
        open=px, high=px, low=px, close=px, volume=[D(volume)] * n,
        entry=[i == entry_at for i in range(n)], exit=[False for _ in range(n)],
    )  # fmt: skip


def test_adv_cap_fills_part_and_reports_it() -> None:
    # ADV = 100 x 1,000 = Rs 1,00,000; 10% = 10,000 = 100 shares; all-in asks 1,000.
    sym = _symbol(40, 1000, entry_at=25)
    res = run_strategy([sym], initial_cash=D(100_000), stops=Stops(), sizing=Sizing(),
                       profile=NEXT_OPEN, schedule=get_fee_schedule("none"), adv_cap_pct=10)  # fmt: skip
    trade = res.trades[0]
    assert trade.quantity == 100 and trade.requested_quantity == 1000
    assert res.partial_entries == 1
    uncapped = run_strategy([sym], initial_cash=D(100_000), stops=Stops(), sizing=Sizing(),
                            profile=NEXT_OPEN, schedule=get_fee_schedule("none"))  # fmt: skip
    assert uncapped.trades[0].quantity == 1000 and uncapped.trades[0].requested_quantity is None


def test_adv_cap_needs_twenty_earlier_bars_and_can_skip() -> None:
    early = _symbol(40, 1000, entry_at=5)  # fills on bar 6: < 20 earlier bars
    res = run_strategy([early], initial_cash=D(100_000), stops=Stops(), sizing=Sizing(),
                       profile=NEXT_OPEN, schedule=get_fee_schedule("none"), adv_cap_pct=10)  # fmt: skip
    assert res.adv_unknown == 1 and res.trades[0].requested_quantity is None
    thin = _symbol(40, 0, entry_at=25)  # zero-volume bars: ADV 0
    res = run_strategy([thin], initial_cash=D(100_000), stops=Stops(), sizing=Sizing(),
                       profile=NEXT_OPEN, schedule=get_fee_schedule("none"), adv_cap_pct=10)  # fmt: skip
    assert not res.trades and res.skip_reasons == {"adv_cap": 1}


def test_template_adv_cap() -> None:
    days = [datetime(2025, 1, 1) + timedelta(days=i) for i in range(60)]
    closes = [D(100) - D(i) / 10 if i < 30 else D(97) + D(i - 30) for i in range(60)]
    bars = list(zip(days, closes, strict=True))
    vols = {d: D(100) for d in days}
    capped = run_backtest(bars, initial_cash=D(100_000), strategy_type="sma_crossover",
                          params={"short_window": 3, "long_window": 10}, volumes=vols,
                          adv_cap_pct=10, fill_rule="next_close")  # fmt: skip
    buys = [t for t in capped.trades if t.side == "buy"]
    assert buys and buys[0].requested_shares is not None
    assert buys[0].shares * buys[0].price <= D(1000) * 2  # about 10% of ~10,000 ADV


# --- rerun honesty ----------------------------------------------------------------


def test_run_saved_before_a42_reruns_identical(client: TestClient, session: Session) -> None:
    """A run saved before A4.2 had no ADV cap, no costs stamp and no gross
    fields on a template summary: it reruns uncapped and ``identical``."""
    seed_walk(session, "AAPL", seed=1)
    uid = user(session)
    res = client.post("/v1/experiments/runs", json={"strategy": body()}, headers=headers(uid))
    row = session.get(ExperimentRun, res.json()["id"])
    assert row is not None
    request = dict(row.request)
    request.pop("adv_cap_pct")
    request.pop("brokerage")
    request["fee_schedule"] = "none"
    row.request = request
    session.add(row)
    session.commit()
    # Store what that request gives, minus the A4.2 fields, as an old run would.
    from stockviz.schemas import StrategyBacktestIn
    from stockviz.services.backtest.registry import as_saved
    from stockviz.services.backtest.strategy_run import execute_strategy

    fresh = execute_strategy(session, StrategyBacktestIn.model_validate(as_saved(request)),
                             user_id=uid).out.model_dump(mode="json")  # fmt: skip
    for key in ("costs", "liquidity"):
        fresh.pop(key)
    for t in fresh["trades"]:
        t.pop("requested_quantity")
        t.pop("exit_adv_pct")
    row.result = fresh
    session.add(row)
    session.commit()
    rerun = client.post(f"/v1/experiments/runs/{row.id}/rerun", headers=headers(uid)).json()
    assert rerun["status"] == "identical", rerun


def test_a_fee_figure_that_changed_is_reported_different() -> None:
    """A stored figure the code now computes differently (e.g. a US run over
    2025 saved with the old flat $20.60 SEC rate) is ``different``."""
    stored = {"summary": {"total_return": 0.1, "total_costs": "5.00"}, "trades": [{"fees": []}]}
    fresh = {"summary": {"total_return": 0.1, "total_costs": "7.12", "gross_return": 0.2},
             "trades": [{"fees": [], "requested_shares": None}], "costs": {}}  # fmt: skip
    assert result_differences(stored, fresh) == ["summary"]
    same = {"summary": {"total_return": 0.1, "total_costs": "5.00", "gross_return": 0.2},
            "trades": [{"fees": [], "requested_shares": None}], "costs": {}}  # fmt: skip
    assert result_differences(stored, same) == []


def test_saved_indian_run_spanning_ipft_split_is_honest(
    client: TestClient, session: Session
) -> None:
    """Fees per fill come from the version on its date: a fill on 27 Feb 2026
    pays exchange + IPFT separately, one on 2 Mar 2026 the folded charge."""
    a = parts("in_delivery_nse_2026", BUY, 100, 2500, date(2026, 2, 27))
    b = parts("in_delivery_nse_2026", BUY, 100, 2500, date(2026, 3, 2))
    assert a["exchange_transaction"] + a["ipft"] == D("7.68")  # 7.43 + 0.25
    assert b["exchange_transaction"] == D("7.68") and "ipft" not in b
