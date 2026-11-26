"""A5.6 (M10.3 stats): "Is my edge real?" over the journal.

Each metric on a hand-built journal, the under-30 rule (29 counts only, 30
an interval identical on a rerun), the bootstrap by seed, the drift
classification, the filters, All books, the imported-fees flag and
isolation. Every fixture is synthetic.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from stockviz.models import ExperimentRun, HoldoutUnlock, Symbol, Trade
from stockviz.models.portfolio import TradeSide
from stockviz.models.trade_plan import TradePlan
from stockviz.schemas import EdgeBacktestOut, EdgeGroupOut, EdgeIntervalOut
from stockviz.services.instruments import resolve_symbol
from stockviz.services.journal import edge
from stockviz.services.journal.edge import Outcome, bootstrap_interval, drift_for, group_stats
from tests.test_imports import _book, _h, _user
from tests.test_journal_entries import _imported_round_trip

START = datetime(2025, 1, 6, 15, 0)


def _o(
    net: float,
    r: float | None = None,
    *,
    i: int = 0,
    days: int = 3,
    followed: bool | None = None,
    source: str = "paper",
    currency: str = "USD",
) -> Outcome:
    return Outcome(
        entry_id=i,
        source=source,
        currency=currency,
        net_pnl=net,
        r=r,
        holding_days=days,
        followed_plan=followed,
        fees_estimated=source == "imported",
        closed_at=START + timedelta(days=i),
        entry_date=(START + timedelta(days=i)).date(),
    )


def _thirty() -> list[Outcome]:
    """18 wins of +100 (1R), 12 losses of -50 (-0.5R); 3 then 5 days held."""
    rows = []
    for i in range(30):
        win = i % 5 not in (1, 3)
        rows.append(
            _o(
                100.0 if win else -50.0,
                1.0 if win else -0.5,
                i=i,
                days=3 if win else 5,
                followed=i % 2 == 0 if i < 20 else None,
            )
        )
    return rows


# --- pure metrics ---------------------------------------------------------------------


def test_each_metric_on_a_hand_built_journal() -> None:
    rows = _thirty()
    g = group_stats(rows, key="overall", label="All", kind="overall")
    assert (g.n, g.wins, g.losses, g.breakeven) == (30, 18, 12, 0)
    assert not g.counts_only and g.counts_only_reason is None
    assert g.win_rate == 0.6
    assert g.avg_win == 100.0 and g.avg_loss == -50.0
    assert g.payoff == 2.0  # 100 / 50
    assert g.profit_factor == 3.0  # 1800 / 600
    assert g.expectancy == 40.0  # (1800 - 600) / 30
    assert g.total_net_pnl == 1200.0
    assert g.n_r == 30 and g.expectancy_r == pytest.approx(0.4)  # (18 - 6) / 30
    assert g.avg_holding_days == pytest.approx(3.8)  # (18 x 3 + 12 x 5) / 30
    # Scored plans: the first 20 entries, every even one followed.
    assert g.adherence_n == 20 and g.adherence_rate == 0.5
    assert g.currency == "USD" and g.money_note is None
    assert g.expectancy_interval is not None and g.expectancy_r_interval is not None
    lo, hi = g.expectancy_interval.low, g.expectancy_interval.high
    assert lo < 40.0 < hi and g.expectancy_interval.level == 0.9


def test_a_breakeven_trade_is_neither_a_win_nor_a_loss() -> None:
    rows = [*_thirty()[:29], _o(0.0, 0.0, i=29)]
    g = group_stats(rows, key="k", label="k", kind="overall")
    assert (g.wins, g.losses, g.breakeven) == (17, 12, 1)
    assert g.win_rate == pytest.approx(17 / 30)


def test_under_thirty_closed_trades_shows_counts_only() -> None:
    rows = _thirty()[:29]
    g = group_stats(rows, key="k", label="k", kind="setup")
    assert g.counts_only and (g.n, g.wins, g.losses) == (29, 17, 12)
    assert g.counts_only_reason is not None and "under the 30 needed" in g.counts_only_reason
    for name in (
        "win_rate", "avg_win", "avg_loss", "payoff", "profit_factor", "expectancy",
        "expectancy_interval", "expectancy_r", "expectancy_r_interval", "adherence_rate",
        "avg_holding_days", "total_net_pnl",
    ):  # fmt: skip
        assert getattr(g, name) is None, name
    assert edge.MIN_EVENTS == 30  # A2.4's constant, reused


def test_thirty_shows_an_interval_identical_on_a_rerun() -> None:
    a = group_stats(_thirty(), key="k", label="k", kind="setup")
    b = group_stats(_thirty(), key="k", label="k", kind="setup")
    assert a.expectancy_r_interval is not None
    assert a.expectancy_r_interval == b.expectancy_r_interval
    assert a.expectancy_interval == b.expectancy_interval


def test_r_needs_thirty_entries_with_a_stop() -> None:
    rows = [_o(o.net_pnl, o.r if o.entry_id < 25 else None, i=o.entry_id) for o in _thirty()]
    g = group_stats(rows, key="k", label="k", kind="overall")
    assert not g.counts_only and g.expectancy == 40.0
    assert g.n_r == 25 and g.expectancy_r is None and g.expectancy_r_interval is None
    assert g.r_note is not None and "25 of these trades" in g.r_note


def test_money_is_never_summed_across_currencies() -> None:
    rows = [
        _o(o.net_pnl, o.r, i=o.entry_id, currency="INR" if o.entry_id % 2 else "USD")
        for o in _thirty()
    ]
    g = group_stats(rows, key="k", label="k", kind="overall")
    assert g.currencies == ["INR", "USD"]
    assert g.expectancy is None and g.total_net_pnl is None and g.avg_win is None
    assert g.money_note is not None and "INR and USD" in g.money_note
    assert g.expectancy_r == pytest.approx(0.4) and g.win_rate == 0.6


def test_bootstrap_is_reproducible_by_seed() -> None:
    values = [((i * 37) % 23) / 10 - 1.0 for i in range(40)]  # spread, not a lattice
    first = bootstrap_interval(values, seed=7)
    assert bootstrap_interval(values, seed=7) == first
    assert bootstrap_interval(values, seed=8) != first
    lo, hi = first
    assert lo < sum(values) / len(values) < hi
    # Mean block 1 is the iid bootstrap: a different draw, the same idea.
    iid = bootstrap_interval(values, seed=7, mean_block=1)
    mean = sum(values) / len(values)
    assert iid != first and iid[0] < mean < iid[1]
    # Every value equal: no spread.
    assert bootstrap_interval([0.5] * 30) == (0.5, 0.5)
    with pytest.raises(ValueError):
        bootstrap_interval([])


# --- drift classification ---------------------------------------------------------------


def _live(n_r: int = 30, lo: float = 0.1, hi: float = 0.7) -> EdgeGroupOut:
    enough = n_r >= 30
    return EdgeGroupOut(
        key="setup:5", label="Breakout v1", kind="setup", setup_version_id=5, n=max(n_r, 30),
        wins=18, losses=12, breakeven=0, counts_only=False, n_r=n_r,
        expectancy_r=0.4 if enough else None,
        expectancy_r_interval=EdgeIntervalOut(low=lo, high=hi, level=0.9) if enough else None,
        win_rate=0.6, avg_holding_days=3.8,
    )  # fmt: skip


def _bt(expectancy_r: float | None = 0.5, closed: int = 40) -> EdgeBacktestOut:
    return EdgeBacktestOut(
        run_id=1, created_at=datetime(2026, 11, 1), ticker="AAPL", closed_trades=closed,
        n_r=closed, expectancy_r=expectancy_r, win_rate=0.5, avg_holding_days=4.0,
        holdout="last_20pct", sample="in_sample", sample_note="In-sample.",
    )  # fmt: skip


def test_drift_classification_cases() -> None:
    inside = drift_for(_live(), _bt(0.5))
    assert inside.status == "consistent"
    assert inside.diff_expectancy_r == pytest.approx(-0.1)
    assert inside.diff_win_rate == pytest.approx(0.1)
    assert inside.diff_avg_holding_days == pytest.approx(-0.2)
    edge_low = drift_for(_live(), _bt(0.1))
    assert edge_low.status == "consistent"  # the interval's ends count as inside
    outside = drift_for(_live(), _bt(0.9))
    assert outside.status == "outside_interval" and outside.diff_expectancy_r == pytest.approx(-0.5)
    few = drift_for(_live(n_r=12), _bt(0.5))
    assert few.status == "too_few_live_trades" and "18 more" in few.text
    assert few.diff_expectancy_r is None
    small_bt = drift_for(_live(), _bt(0.5, closed=12))
    assert small_bt.status == "too_few_backtest_trades"
    none = drift_for(_live(), None)
    assert none.status == "no_backtest" and none.text == "No backtest for this setup."
    no_r = drift_for(_live(), _bt(None))
    assert no_r.status == "backtest_no_r"


# --- through the API --------------------------------------------------------------------


def _aapl(session: Session) -> int:
    if session.get(Symbol, "AAPL") is None:
        session.add(Symbol(ticker="AAPL", name="Apple", currency="USD"))
        session.commit()
    inst = resolve_symbol(session, "AAPL")
    assert inst is not None and inst.id is not None
    return inst.id


def _setup(client: TestClient, uid: int, name: str) -> int:
    r = client.post(
        "/v1/setups", json={"name": name, "rule": "close > sma(close, 50)"}, headers=_h(uid)
    )
    assert r.status_code == 201, r.text
    return r.json()["latest_version"]["id"]


def _trip(
    session: Session,
    uid: int,
    book: int,
    instrument: int,
    *,
    day: int,
    buy: str,
    sell: str,
    stop: str | None = "95",
    version: int | None = None,
) -> None:
    """A closed paper round trip of 10 shares, with a plan locked at the buy."""
    when = START + timedelta(days=day)
    plan_id = None
    if stop is not None or version is not None:
        plan = TradePlan(
            user_id=uid, portfolio_id=book, instrument_id=instrument, source="paper",
            side="long", planned_entry=Decimal(buy), planned_stop=Decimal(stop) if stop else None,
            planned_size=Decimal(10), setup_version_id=version, status="closed",
            locked_at=when, first_fill_at=when, created_at=when - timedelta(hours=1),
        )  # fmt: skip
        session.add(plan)
        session.commit()
        plan_id = plan.id
    for side, price, at in ((TradeSide.BUY, buy, when), (TradeSide.SELL, sell, when + timedelta(days=2))):  # fmt: skip
        session.add(
            Trade(
                portfolio_id=book, ticker="AAPL", instrument_id=instrument, side=side,
                quantity=Decimal(10), price=Decimal(price), ts=at, fx_rate=Decimal(1),
                fees=Decimal(0), trade_plan_id=plan_id,
            )
        )  # fmt: skip
    session.commit()


def _stats(client: TestClient, uid: int, query: str = "") -> dict:
    r = client.get(f"/v1/journal/stats{query}", headers=_h(uid))
    assert r.status_code == 200, r.text
    return r.json()


def _journal(session: Session, client: TestClient) -> tuple[int, int, int, int, int]:
    """35 trips on setup A (21 wins of +50, 14 losses of -50; stop 95 = 1R),
    4 on setup B, 2 with no plan; tags on a few."""
    instrument = _aapl(session)
    uid = _user(session)
    book = _book(client, uid, kind="paper", base_currency="USD")
    a = _setup(client, uid, "Breakout")
    b = _setup(client, uid, "Pullback")
    for i in range(35):
        _trip(session, uid, book, instrument, day=3 * i, buy="100",
              sell="105" if i % 5 not in (1, 3) else "95", version=a)  # fmt: skip
    for i in range(4):
        _trip(session, uid, book, instrument, day=200 + 3 * i, buy="100", sell="110", version=b)
    for i in range(2):
        _trip(session, uid, book, instrument, day=300 + 3 * i, buy="100", sell="90", stop=None)
    return uid, book, a, b, instrument


def _tag(client: TestClient, uid: int, entry_id: int, **tags: list[str]) -> None:
    r = client.patch(f"/v1/journal/entries/{entry_id}", json=tags, headers=_h(uid))
    assert r.status_code == 200, r.text


def test_stats_over_a_paper_journal(session: Session, client: TestClient) -> None:
    uid, _book_id, a, b, _ = _journal(session, client)
    s = _stats(client, uid)
    assert s["seed"] == edge.SEED and s["resamples"] == 5000 and s["mean_block"] == 3
    assert s["interval_level"] == 0.9 and s["min_closed"] == 30
    assert s["sources_included"] == ["paper"] and not s["imported_fees_estimated"]
    o = s["overall"]
    assert o["n"] == 41 and not o["counts_only"]
    # 21 x 50 + 4 x 100 - 14 x 50 - 2 x 100 = 550 over 41 trades.
    assert o["total_net_pnl"] == 550.0 and o["expectancy"] == round(550 / 41, 2)
    setups = {g["setup_version_id"]: g for g in s["by_setup"]}
    ga, gb = setups[a], setups[b]
    assert ga["n"] == 35 and not ga["counts_only"] and ga["label"] == "Breakout v1"
    assert ga["win_rate"] == 0.6 and ga["expectancy_r"] == pytest.approx(0.2)
    assert ga["expectancy_r_interval"]["low"] < 0.2 < ga["expectancy_r_interval"]["high"]
    assert ga["avg_holding_days"] == 2.0
    assert gb["counts_only"] and gb["n"] == 4 and gb["wins"] == 4 and gb["expectancy"] is None
    assert setups[None]["label"] == "No setup" and setups[None]["n"] == 2
    assert [g["key"] for g in s["by_source"]] == ["source:paper"]
    assert any("not advice" in h.lower() for h in s["honesty"])
    assert any("survivorship" in h.lower() for h in s["honesty"])
    # Rerun: the same interval.
    assert _stats(client, uid)["overall"] == o
    # Drift: no saved backtest for either setup.
    drift = {d["setup_version_id"]: d for d in s["drift"]}
    assert drift[a]["status"] == "no_backtest" and drift[b]["status"] == "no_backtest"


def test_filters_book_and_isolation(session: Session, client: TestClient) -> None:
    uid, book, _a, b, _ = _journal(session, client)
    entries = client.get(f"/v1/journal/entries?book={book}&limit=200", headers=_h(uid)).json()[
        "entries"
    ]
    oldest = sorted(entries, key=lambda e: e["opened_at"])
    for e in oldest[:3]:
        _tag(client, uid, e["id"], setup_tags=["Gap"], mistake_tags=["Late"])
    assert _stats(client, uid, f"?setup_version_id={b}")["overall"]["n"] == 4
    tagged = _stats(client, uid, "?tag=gap")
    assert tagged["overall"]["n"] == 3 and tagged["overall"]["counts_only"]
    assert [g["label"] for g in tagged["by_setup_tag"]] == ["Gap"]
    assert [g["label"] for g in tagged["by_mistake_tag"]] == ["Late"]
    # Entry dates: the first trips are in January 2025.
    jan = _stats(client, uid, "?from=2025-01-01&to=2025-01-31")
    assert jan["overall"]["n"] == 9  # days 0, 3, ..., 24
    assert _stats(client, uid, "?source=replay")["overall"]["n"] == 0
    assert _stats(client, uid, "?source=all")["overall"]["n"] == 41
    assert _stats(client, uid, f"?book={book}")["overall"]["n"] == 41
    assert _stats(client, uid, "?book=all")["overall"]["n"] == 41
    bad = client.get("/v1/journal/stats?from=2025-02-01&to=2025-01-01", headers=_h(uid))
    assert bad.status_code == 400

    # Another user: their book is 404, and none of these entries are theirs.
    other = _user(session)
    assert client.get(f"/v1/journal/stats?book={book}", headers=_h(other)).status_code == 404
    theirs = _stats(client, other)
    assert theirs["overall"]["n"] == 0 and theirs["overall"]["counts_only"]
    assert theirs["by_setup"] == [] and theirs["drift"] == []
    assert client.get("/v1/journal/stats").status_code == 401


def test_open_entries_are_counted_not_used(session: Session, client: TestClient) -> None:
    instrument = _aapl(session)
    uid = _user(session)
    book = _book(client, uid, kind="paper", base_currency="USD")
    _trip(session, uid, book, instrument, day=0, buy="100", sell="105")
    session.add(
        Trade(
            portfolio_id=book, ticker="AAPL", instrument_id=instrument, side=TradeSide.BUY,
            quantity=Decimal(5), price=Decimal(100), ts=START + timedelta(days=30),
            fx_rate=Decimal(1), fees=Decimal(0),
        )
    )  # fmt: skip
    session.commit()
    s = _stats(client, uid)
    assert s["overall"]["n"] == 1 and s["open_excluded"] == 1


def test_imported_entries_flag_estimated_fees(session: Session, client: TestClient) -> None:
    uid, book, _plan = _imported_round_trip(session, client)
    s = _stats(client, uid)
    assert s["sources_included"] == ["imported"] and s["imported_fees_estimated"]
    assert s["overall"]["includes_imported"] and s["overall"]["n"] == 1
    assert any("estimated" in h for h in s["honesty"])
    assert [g["label"] for g in s["by_source"]] == ["Imported"]
    # Imported and paper are not pooled with replay; `source=paper` leaves it out.
    assert _stats(client, uid, "?source=paper")["overall"]["n"] == 0
    assert _stats(client, uid, f"?book={book}")["imported_fees_estimated"]


def test_short_entries_win_or_lose_by_net_pnl(session: Session, client: TestClient) -> None:
    from tests.test_imports import _commit, _csv, _row, _symbols
    from tests.test_journal_entries import _reliance_week

    _symbols(session)
    _reliance_week(session)
    uid = _user(session)
    book = _book(client, uid)
    body = _csv(
        # A winning short (sold 1210, bought back 1200) and a losing one.
        _row("RELIANCE", "2025-05-05", "sell", "10", "1210", "S1", time="09:30:00"),
        _row("RELIANCE", "2025-05-05", "buy", "10", "1200", "S2", time="14:00:00"),
        _row("RELIANCE", "2025-05-06", "sell", "10", "1200", "S3", time="09:30:00"),
        _row("RELIANCE", "2025-05-06", "buy", "10", "1225", "S4", time="14:00:00"),
    )
    assert _commit(client, uid, book, body).status_code == 200
    entries = client.get("/v1/journal/entries", headers=_h(uid)).json()["entries"]
    assert [e["side"] for e in entries] == ["short", "short"]
    nets = sorted(Decimal(e["net_pnl"]) for e in entries)
    assert nets[0] < 0 < nets[1]
    o = _stats(client, uid)["overall"]
    assert o["n"] == 2 and o["wins"] == 1 and o["losses"] == 1 and o["counts_only"]
    assert o["n_r"] == 0  # no plan on a short, so no R


def _run(
    session: Session, uid: int, version: int, rs: list[float], *, days: int = 4, when: datetime
) -> ExperimentRun:
    trades = [
        {"entry_date": "2024-01-02", "exit_date": (date(2024, 1, 2) + timedelta(days=days)).isoformat(),
         "pnl": "10" if r > 0 else "-10", "r_multiple": r, "open": False}
        for r in rs
    ] + [{"entry_date": "2024-06-03", "exit_date": "2024-06-04", "pnl": "1", "r_multiple": 9.0, "open": True}]  # fmt: skip
    row = ExperimentRun(
        user_id=uid, kind="strategy", ticker="AAPL", request={}, execution_profile="next_open",
        fee_schedule="none", code_version="test", dataset_fingerprint="0" * 64, bar_count=10,
        result={
            "trades": trades,
            "window": {"holdout": "last_20pct", "to_date": "2024-08-01",
                       "holdout_from": "2024-08-02", "holdout_to": "2024-12-31"},
        },
        setup_version_id=version, created_at=when,
    )  # fmt: skip
    session.add(row)
    session.commit()
    return row


def test_drift_reads_the_newest_saved_backtest(
    session: Session, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    uid, _book_id, a, b, _ = _journal(session, client)
    _run(session, uid, a, [3.0] * 40, when=datetime(2026, 1, 1))  # older: far outside
    newest = _run(session, uid, a, [1.0, -0.5] * 20, when=datetime(2026, 2, 1))
    _run(session, uid, b, [1.0] * 40, when=datetime(2026, 2, 1))
    other = _user(session)
    _run(session, other, a, [9.0] * 40, when=datetime(2026, 3, 1))  # never someone else's

    drift = {d["setup_version_id"]: d for d in _stats(client, uid)["drift"]}
    da = drift[a]
    assert da["backtest"]["run_id"] == newest.id
    assert da["backtest"]["closed_trades"] == 40  # the open trade is left out
    assert da["backtest"]["expectancy_r"] == 0.25 and da["backtest"]["win_rate"] == 0.5
    assert da["backtest"]["avg_holding_days"] == 4.0
    assert da["backtest"]["sample"] == "in_sample"
    assert "holdout (2024-08-02 to 2024-12-31) is still locked" in da["backtest"]["sample_note"]
    lo, hi = da["live_interval"]["low"], da["live_interval"]["high"]
    assert da["status"] == ("consistent" if lo <= 0.25 <= hi else "outside_interval")
    assert da["diff_expectancy_r"] == pytest.approx(0.2 - 0.25)
    assert da["diff_avg_holding_days"] == pytest.approx(-2.0)
    assert drift[b]["status"] == "too_few_live_trades" and "26 more" in drift[b]["text"]

    # A holdout unlocked for the run's family: said so.
    monkeypatch.setattr(edge, "family_key", lambda _result: "fam")
    session.add(
        HoldoutUnlock(
            user_id=uid, family_key="fam", family_label="x", holdout_from=date(2024, 8, 2),
            holdout_to=date(2024, 12, 31), unlocked_at=datetime(2026, 2, 2, tzinfo=UTC),
        )
    )  # fmt: skip
    session.commit()
    seen = {d["setup_version_id"]: d for d in _stats(client, uid)["drift"]}[a]
    assert seen["backtest"]["sample"] == "holdout_seen"
    assert seen["backtest"]["unlocked_at"] is not None
