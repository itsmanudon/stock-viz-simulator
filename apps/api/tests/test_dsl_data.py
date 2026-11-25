"""Rule DSL data layer and CLI (A2.1): loading by instrument, warm-up, the
fundamentals binding against ``valuation()``, delivery, news, benchmark,
and ``stockviz.cli rule-check``."""

# pandas-stubs type index labels as Hashable / Index; every value here is a
# Timestamp or a float by construction.
# pyright: reportAttributeAccessIssue=false, reportArgumentType=false

from __future__ import annotations

import math
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest
from sqlmodel import Session

from stockviz import cli
from stockviz.models import (
    AegisAnalysis,
    AegisDocument,
    AegisDocumentEntity,
    AegisEvent,
    AegisMapping,
    FxRate,
    PriceBar,
    Symbol,
)
from stockviz.models.data_file import DataFile
from stockviz.models.eod import EodExtras
from stockviz.services.dsl import Needs, compile_rule, evaluate_at, load_symbol, vector
from stockviz.services.dsl.bindings import FUNDAMENTAL_METRICS
from stockviz.services.fundamentals.store import FactRecord, record_facts
from stockviz.services.fundamentals.valuation import valuation
from stockviz.services.instruments import instrument_ids
from tests.dsl_fixtures import sessions
from tests.symbols import seed_symbols

DAYS = list(sessions("XNYS", date(2024, 1, 2), date(2024, 12, 31)))


def _bars(session: Session, ticker: str, days=DAYS, start: float = 100.0) -> None:
    for i, day in enumerate(days):
        c = Decimal(str(round(start + i * 0.5 + (i % 7), 2)))
        session.add(
            PriceBar(ticker=ticker, ts=datetime.combine(day, time.min), interval="1d", open=c - 1,
                     high=c + 2, low=c - 2, close=c, volume=1000 + i, source="test")
        )  # fmt: skip
    session.commit()


def test_bars_load_by_instrument_with_the_rules_warm_up(session: Session) -> None:
    seed_symbols(session, "AAPL")
    _bars(session, "AAPL")
    rule = compile_rule("close > sma(close, 20)")
    end = DAYS[-1]
    window = load_symbol(session, "AAPL", end=end, start=DAYS[-5], lookback=rule.lookback)
    assert len(window.bars) == 5 + 19
    full = load_symbol(session, "AAPL", end=end)
    assert len(full.bars) == len(DAYS)
    # The judged bars agree: the warm-up covers the window exactly.
    tail = vector(rule, full).iloc[-5:]
    pd.testing.assert_series_equal(vector(rule, window).iloc[-5:], tail)
    assert vector(rule, window).iloc[:19].isna().all()
    # A window after the newest bar still warms up the newest bar.
    stale = load_symbol(session, "AAPL", end=date(2030, 1, 2), start=date(2030, 1, 2), lookback=19)
    assert len(stale.bars) == 20 and stale.bars.index[-1].date() == DAYS[-1]
    assert vector(rule, stale).iloc[-1] == tail.iloc[-1]
    early = load_symbol(session, "AAPL", end=DAYS[10])
    assert early.bars.index[-1].date() == DAYS[10]


def _seed_fundamentals(session: Session) -> None:
    seed_symbols(session, "INFY.NS", currency="INR")
    days = list(sessions("XNSE", date(2025, 1, 1), date(2026, 11, 20)))
    _bars(session, "INFY.NS", days, start=1400)
    iid = instrument_ids(session, ["INFY.NS"])["INFY.NS"]

    def fact(concept, ptype, end, value, known, unit="USD", source="edgar"):
        return FactRecord(concept=concept, period_type=ptype, period_end=end,
                          value=Decimal(str(value)), unit=unit,
                          currency=None if unit == "shares" else "USD", available_at=known,
                          point_in_time=source == "edgar", source=source,
                          source_concept=f"test:{concept}")  # fmt: skip

    records = [fact("revenue", "annual", date(2025, 3, 31), 16000, date(2025, 5, 1))]
    quarters = [date(2025, 6, 30), date(2025, 9, 30), date(2025, 12, 31), date(2026, 3, 31),
                date(2026, 6, 30), date(2026, 9, 30)]  # fmt: skip
    for i, end in enumerate(quarters):
        known = end + timedelta(days=30)
        records += [
            fact("revenue", "quarter", end, 5000 + 100 * i, known),
            fact("net_income", "quarter", end, 1000 - 400 * (i == 3), known),
            fact("ebitda", "quarter", end, 1500, known),
            fact("gross_profit", "quarter", end, 2000, known),
            fact("operating_income", "quarter", end, 1200, known),
            fact("dividends_paid", "quarter", end, 100, known),
            fact("equity", "instant", end, 36000 + 1000 * i, known),
            fact("cash", "instant", end, 2000, known),
            fact("total_debt", "instant", end, 10000, known),
            fact("total_assets", "instant", end, 60000, known),
            fact("current_assets", "instant", end, 9000, known),
            fact("current_liabilities", "instant", end, 6000, known),
            fact("shares_outstanding", "instant", end, 4000, known, unit="shares"),
        ]
    # yfinance repeats one quarter later with another value: EDGAR wins.
    records.append(
        fact("revenue", "quarter", quarters[2], 9999, date(2026, 3, 1), source="yfinance")
    )
    record_facts(session, iid, records)
    for i, day in enumerate(d for d in days if d.day in (1, 15)):
        session.add(
            FxRate(currency="INR", date=day, usd_rate=Decimal("0.012") + Decimal(i) / 100000)
        )
    session.commit()


def test_fundamentals_binding_equals_valuation_on_every_checked_date(session: Session) -> None:
    _seed_fundamentals(session)
    data = load_symbol(session, "INFY.NS", end=date(2026, 11, 20), needs=Needs(fundamentals=True))
    days = [ts.date() for ts in data.bars.index]
    checked = days[::9] + days[-3:]
    for metric in FUNDAMENTAL_METRICS:
        values = vector(compile_rule(f"fundamental.{metric}", require_condition=False), data)
        for day in checked:
            want = valuation(session, "INFY.NS", day).value(metric)
            got = values[pd.Timestamp(day)]
            if want is None:
                assert math.isnan(got), (metric, day, got)
            else:
                assert got == pytest.approx(want, rel=1e-9), (metric, day)
    # The reasons are valuation's.
    pe_loss = next(d for d in checked if valuation(session, "INFY.NS", d).value("pe") is None
                   and d > date(2025, 8, 1))  # fmt: skip
    expected = next(
        m.reason for m in valuation(session, "INFY.NS", pe_loss).metrics if m.key == "pe"
    )
    outcome, _ = evaluate_at("fundamental.pe < 30", data.cut(pe_loss), pe_loss)
    assert outcome.reasons == (f"fundamental.pe: {expected}",)


def test_delivery_comes_from_eod_extras_and_is_unknown_without_it(session: Session) -> None:
    seed_symbols(session, "RELIANCE.NS", currency="INR")
    days = list(sessions("XNSE", date(2024, 1, 1), date(2024, 3, 1)))
    _bars(session, "RELIANCE.NS", days)
    rule = compile_rule("delivery_pct > 50")
    data = load_symbol(session, "RELIANCE.NS", end=days[-1], needs=rule.needs)
    assert not data.delivery_loaded
    outcome, _ = evaluate_at(rule, data, days[-1])
    assert outcome.reasons == ("delivery_pct: no delivery data for RELIANCE.NS (eod_extras)",)

    iid = instrument_ids(session, ["RELIANCE.NS"])["RELIANCE.NS"]
    session.add(DataFile(id=1, source="nse_sec_full", file_name="x.csv", sha256="0" * 64,
                         size_bytes=1, archived_path="x", parse_status="parsed"))  # fmt: skip
    session.flush()
    session.add(EodExtras(instrument_id=iid, session_date=days[-1], series="EQ", deliverable_qty=10,
                          delivery_pct=Decimal("61.5"), data_file_id=1))  # fmt: skip
    session.add(EodExtras(instrument_id=iid, session_date=days[-1], series="BE", deliverable_qty=1,
                          delivery_pct=Decimal("10"), data_file_id=1))  # fmt: skip
    session.commit()
    data = load_symbol(session, "RELIANCE.NS", end=days[-1], needs=rule.needs)
    assert data.delivery_loaded
    assert data.bars["delivery_pct"].iloc[-1] == 61.5  # EQ over BE
    assert vector(rule, data).iloc[-1] is np.True_ or bool(vector(rule, data).iloc[-1])
    outcome, _ = evaluate_at(rule, data, days[-2])
    assert outcome.reasons == (f"delivery_pct: no delivery data on {days[-2].isoformat()}",)


def _doc(session: Session, ticker: str, doc: str, at: datetime, label: str, event: str | None):
    if session.get(AegisMapping, f"map_{ticker}") is None:
        session.add(AegisMapping(mapping_id=f"map_{ticker}", entity_id=f"ent_{ticker}",
                                 scheme="provider_id", identifier=f"stockviz:{ticker}",
                                 created_at=datetime(2024, 1, 1)))  # fmt: skip
    session.add(AegisDocument(document_id=doc, source_id="s", source_name="Wire", title=doc,
                              first_seen_at=at, available_at=at, last_signed_at=at))  # fmt: skip
    session.flush()
    session.add(AegisDocumentEntity(document_id=doc, entity_id=f"ent_{ticker}", canonical_name=ticker,
                                    kind="organization", resolution_analysis_id=f"r_{doc}",
                                    confidence=1.0))  # fmt: skip
    session.add(AegisAnalysis(analysis_id=f"s_{doc}", document_id=doc, analysis_type="sentiment",
                              provider="p", model_name="m", model_version="1",
                              configuration_hash="0" * 64, available_at=at, label=label,
                              score=-0.5, outputs=[]))  # fmt: skip
    if event:
        session.add(AegisEvent(event_id=f"e_{doc}", revision=1, document_id=doc, event_type=event,
                               available_at=at, evidence_kind="text"))  # fmt: skip


def test_news_and_benchmark_load_point_in_time(session: Session) -> None:
    seed_symbols(session, "AAPL")
    session.add(Symbol(ticker="^GSPC", name="S&P 500"))
    session.commit()
    _bars(session, "AAPL")
    _bars(session, "^GSPC", start=4000)
    day = DAYS[100]
    # 22:00 UTC: after that day's New York close, so it counts from the next session.
    late = datetime.combine(day, time(22, 0))
    early = datetime.combine(day, time(15, 0))
    _doc(session, "AAPL", "d1", early, "negative", "Earnings")
    _doc(session, "AAPL", "d2", late, "negative", None)
    _doc(session, "MSFT", "d3", early - timedelta(days=30), "positive", None)  # coverage start
    session.commit()
    rule = compile_rule('news.count(7, sentiment="negative") >= 2 and rs(20) > -100')
    data = load_symbol(session, "AAPL", end=DAYS[-1], needs=rule.needs)
    assert data.benchmark is not None and data.benchmark_ticker == "^GSPC"
    counts = vector(
        compile_rule('news.count(7, sentiment="negative")', require_condition=False), data
    )
    assert counts[pd.Timestamp(DAYS[60])] != counts[pd.Timestamp(DAYS[60])]  # before coverage: NaN
    assert counts[pd.Timestamp(DAYS[99])] == 0
    assert counts[pd.Timestamp(day)] == 1
    assert counts[pd.Timestamp(DAYS[101])] == 2
    events = vector(
        compile_rule('news.count(7, event_type="earnings")', require_condition=False), data
    )
    assert events[pd.Timestamp(day)] == 1
    assert bool(vector(rule, data)[pd.Timestamp(DAYS[101])])
    # Point mode on a load that ends on the day sees only the early document.
    cut = load_symbol(session, "AAPL", end=day, needs=rule.needs)
    outcome, _ = evaluate_at(rule, cut, day)
    assert outcome.status == "not_met"


def test_rule_check_cli(session: Session, engine, monkeypatch, capsys) -> None:
    seed_symbols(session, "AAPL")
    _bars(session, "AAPL")
    monkeypatch.setattr(cli, "engine", engine)
    code = cli.main(["rule-check", "close  >  sma( close , 20 )", "AAPL", "NOPE",
                     "--date", DAYS[-1].isoformat(), "--explain"])  # fmt: skip
    out = capsys.readouterr().out
    assert code == 1  # NOPE is unknown
    assert "canonical: close > sma(close, 20)" in out
    assert f"hash:      {compile_rule('close > sma(close, 20)').hash}" in out
    assert f"AAPL {DAYS[-1].isoformat()}: " in out and "NOPE: unknown symbol" in out
    assert "  sma(close, 20) = " in out

    assert cli.main(["rule-check", "close > sma(close 20)", "AAPL"]) == 2
    out = capsys.readouterr().out
    assert "syntax error at line 1, column 19" in out and "^" in out
    assert cli.main(["rule-check", "sma(close, 20)", "AAPL"]) == 2
    assert "must be a condition" in capsys.readouterr().out

    code = cli.main(["rule-check", "close > sma(close, 400)", "AAPL", "--date", "2030-01-01"])
    out = capsys.readouterr().out
    assert code == 0
    assert f"AAPL {DAYS[-1].isoformat()} (latest bar; session 2030-01-01): unknown" in out
    assert "not enough history" in out


def test_rule_check_defaults_to_the_latest_completed_session(session, engine, monkeypatch, capsys):
    seed_symbols(session, "AAPL")
    _bars(session, "AAPL")
    monkeypatch.setattr(cli, "engine", engine)

    class Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2024, 12, 31, 23, 0, tzinfo=UTC)

    monkeypatch.setattr(cli, "datetime", Frozen)
    assert cli.main(["rule-check", "close > 0", "AAPL"]) == 0
    assert f"AAPL {date(2024, 12, 31).isoformat()}: met" in capsys.readouterr().out
