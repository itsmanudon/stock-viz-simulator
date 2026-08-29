"""CLI safety tests for private, non-persistent Massive shadow execution."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from stockviz import cli
from stockviz.services.ingest.bar_semantics import AdjustmentSemantics, SessionScope
from stockviz.services.ingest.prices import BarRecord


def _bar(source: str, scope: SessionScope) -> BarRecord:
    return BarRecord(
        ticker="AAPL",
        ts=datetime(2025, 1, 2),
        interval="1d",
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal("100.5"),
        volume=Decimal("1000.5000"),
        source=source,
        adjustment_semantics=AdjustmentSemantics.SPLIT_ADJUSTED,
        session_scope=scope,
    )


def test_market_shadow_refuses_to_run_without_massive_key(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "get_settings", lambda: SimpleNamespace(massive_api_key=""))
    monkeypatch.setattr(
        cli,
        "run_market_shadow",
        lambda **_kwargs: pytest.fail("runner must not execute without a key"),
    )

    result = cli.main(["market-shadow", "AAPL", "--from", "2025-01-01", "--to", "2025-01-02"])

    assert result == 2
    assert "MASSIVE_API_KEY" in capsys.readouterr().err


@pytest.mark.parametrize(
    "arguments",
    [
        ["--from", "bad-date", "--to", "2025-01-02"],
        ["--from", "2025-01-03", "--to", "2025-01-02"],
    ],
)
def test_market_shadow_rejects_invalid_ranges(monkeypatch, capsys, arguments) -> None:
    monkeypatch.setattr(cli, "get_settings", lambda: SimpleNamespace(massive_api_key="secret"))

    result = cli.main(["market-shadow", *arguments])

    assert result == 2
    assert "date range" in capsys.readouterr().err.lower()


def test_market_shadow_uses_representative_defaults_and_prints_paths(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    captured: dict[str, object] = {}
    run = object()

    def fake_runner(**kwargs):
        captured.update(kwargs)
        return run

    def fake_writer(actual_run, output_dir):
        assert actual_run is run
        assert output_dir == tmp_path
        return tmp_path / "run" / "report.json", tmp_path / "run" / "report.md"

    monkeypatch.setattr(cli, "get_settings", lambda: SimpleNamespace(massive_api_key="secret"))
    monkeypatch.setattr(cli, "run_market_shadow", fake_runner)
    monkeypatch.setattr(cli, "write_shadow_report", fake_writer)
    monkeypatch.setattr(cli, "Session", lambda *_args, **_kwargs: pytest.fail("no DB session"))

    result = cli.main(
        [
            "market-shadow",
            "--from",
            "2025-01-01",
            "--to",
            "2025-01-31",
            "--output-dir",
            str(tmp_path),
        ]
    )

    assert result == 0
    assert captured["symbols"] == ["AAPL", "MSFT", "NVDA", "AMZN", "META", "TSLA", "JPM"]
    assert captured["start"] == date(2025, 1, 1)
    assert captured["end"] == date(2025, 1, 31)
    assert captured["api_key"] == "secret"
    output = capsys.readouterr().out
    assert "report.json" in output
    assert "report.md" in output


def test_market_shadow_normalizes_explicit_symbols(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def fake_runner(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(cli, "get_settings", lambda: SimpleNamespace(massive_api_key="secret"))
    monkeypatch.setattr(cli, "run_market_shadow", fake_runner)
    monkeypatch.setattr(
        cli,
        "write_shadow_report",
        lambda _run, _path: (tmp_path / "report.json", tmp_path / "report.md"),
    )

    assert (
        cli.main(
            [
                "market-shadow",
                "aapl",
                "msft",
                "--from",
                "2025-01-01",
                "--to",
                "2025-01-02",
                "--output-dir",
                str(tmp_path),
            ]
        )
        == 0
    )
    assert captured["symbols"] == ["AAPL", "MSFT"]


def test_runner_stays_in_memory_and_independently_samples_session_scope(monkeypatch) -> None:
    reference = _bar("yfinance", SessionScope.REGULAR)
    candidate = _bar("massive", SessionScope.PROVIDER_DAILY)
    open_close = SimpleNamespace(
        open=candidate.open,
        high=candidate.high,
        low=candidate.low,
        close=candidate.close,
        volume=candidate.volume,
    )
    monkeypatch.setattr(cli, "fetch_yfinance_daily", lambda *_args, **_kwargs: [reference])
    monkeypatch.setattr(cli, "fetch_massive_daily", lambda *_args, **_kwargs: [candidate])
    monkeypatch.setattr(cli, "fetch_massive_splits", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(cli, "fetch_massive_dividends", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(cli, "fetch_massive_open_close", lambda *_args, **_kwargs: open_close)
    monkeypatch.setattr(cli, "Session", lambda *_args, **_kwargs: pytest.fail("no DB session"))
    monkeypatch.setattr(cli, "ingest_ticker", lambda *_args, **_kwargs: pytest.fail("no persistence"))

    run = cli.run_market_shadow(
        symbols=["AAPL"],
        start=date(2025, 1, 1),
        end=date(2025, 1, 3),
        api_key="secret",
        precision_symbols=[],
    )

    assert run.symbols["AAPL"].common_sessions == 1
    assert len(run.session_scope_samples) == 1
    assert run.session_scope_samples[0].passed is True
    assert run.volume_precision.maximum_fractional_digits == 4
    assert run.technical_gate == "passed_private_shadow_evidence"
    assert run.licensing_gate == "not_approved_individual_subscription"
    assert run.cutover_recommendation == "do_not_cut_over"
