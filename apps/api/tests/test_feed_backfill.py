"""A6.3: ``intraday-backfill`` (plan, idempotent apply, job_runs) and ``/v1/broker/feeds``.

Hand-written fixtures through a fake HTTP function: no provider is called.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from jose import jwt as jose_jwt
from sqlmodel import Session, col, func, select

from stockviz.models import JobRun, User
from stockviz.models.intraday import IntradayBar
from stockviz.services.brokers import FEED_BACKFILL_JOBS, record_provider_run
from stockviz.services.feeds import backfill as bf
from stockviz.services.feeds import registry
from stockviz.services.feeds.alpaca import AlpacaFeed
from stockviz.services.feeds.base import FeedBar
from stockviz.services.feeds.massive import MassiveFeed
from stockviz.services.feeds.status import feed_statuses
from stockviz.services.feeds.tiingo import TiingoFeed
from stockviz.settings import get_settings
from tests.feed_helpers import FakeClock, FakeHttp, fixture, response
from tests.symbols import seed_symbols

KEY = "PKFAKE-BACKFILL-KEY"
SECRET = "fake-backfill-SECRET"
NOW = datetime(2025, 3, 10, 12, tzinfo=UTC)
OPEN = datetime(2025, 3, 3, 14, 30, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bf, "now_utc", lambda: NOW)


# --- Plan ---------------------------------------------------------------------


def test_plan_counts_sessions_calls_and_wait() -> None:
    week = (date(2025, 3, 3), date(2025, 3, 9))
    alpaca = bf.make_plan(AlpacaFeed(key=KEY, secret=SECRET), ["aapl", "MSFT", "AAPL"], *week, NOW)
    assert alpaca.symbols == ("AAPL", "MSFT") and alpaca.feed == "iex"
    assert alpaca.window is not None and len(alpaca.window.sessions) == 5
    assert alpaca.window.minutes == 5 * 390
    assert alpaca.window.start == OPEN
    assert alpaca.calls == 2 and alpaca.seconds(AlpacaFeed()) == 0
    assert alpaca.rate_limits == "200 per minute"
    year = bf.make_plan(AlpacaFeed(), ["AAPL"], date(2024, 3, 1), date(2025, 2, 28), NOW)
    assert year.calls_per_symbol == 10  # 251 sessions x 390 / 10,000
    tiingo = bf.make_plan(TiingoFeed(), ["AAPL"] * 1 + ["MSFT"], *week, NOW)
    assert tiingo.calls_per_symbol == 1 and tiingo.rate_limits == "50 per hour, 1000 per day"
    massive = bf.make_plan(MassiveFeed(), [f"T{i}" for i in range(10)], *week, NOW)
    assert massive.feed == "sip" and massive.calls == 10
    assert massive.seconds(MassiveFeed()) == pytest.approx(60.0)


def test_plan_clips_massive_history_and_alpaca_sip() -> None:
    old = bf.make_plan(MassiveFeed(), ["MSFT"], date(2020, 1, 1), date(2025, 3, 7), NOW)
    assert old.window is not None
    assert old.window.start.date() >= date(2023, 3, 11)
    assert any("2 years" in n for n in old.window.notes)
    during = datetime(2025, 3, 3, 20, 0, tzinfo=UTC)
    sip = bf.make_plan(AlpacaFeed(feed="sip"), ["AAPL"], date(2025, 3, 3), date(2025, 3, 3), during)
    assert sip.window is not None and sip.window.end == during - timedelta(minutes=15)
    assert sip.feed == "sip" and any("15 minutes" in n for n in sip.window.notes)
    iex = bf.make_plan(AlpacaFeed(), ["AAPL"], date(2025, 3, 3), date(2025, 3, 3), during)
    assert iex.window is not None and iex.window.end == during
    weekend = bf.make_plan(AlpacaFeed(), ["AAPL"], date(2025, 3, 8), date(2025, 3, 9), NOW)
    assert weekend.window is None and weekend.calls == 0


def test_plan_refuses_indian_tickers() -> None:
    with pytest.raises(ValueError):
        bf.make_plan(AlpacaFeed(), ["RELIANCE.NS"], date(2025, 3, 3), date(2025, 3, 3), NOW)


def test_rows_keep_regular_minutes_and_clip_availability() -> None:
    plan = bf.make_plan(AlpacaFeed(), ["AAPL"], date(2024, 11, 29), date(2024, 11, 29), NOW)
    assert plan.window is not None  # the day after Thanksgiving closes at 13:00 New York
    close = plan.window.sessions[0].close
    assert close == datetime(2024, 11, 29, 18, 0, tzinfo=UTC)

    def bar(ts: datetime) -> FeedBar:
        p = Decimal("10")
        return FeedBar("AAPL", ts, p, p, p, p, 5, "iex", "alpaca_iex")

    rows, off = bf._rows(
        [bar(close - timedelta(minutes=1)), bar(close), bar(close + timedelta(hours=1))],
        7,
        plan.window.sessions,
    )
    assert off == 2 and len(rows) == 1
    assert rows[0]["available_at"] == close.replace(tzinfo=None)
    assert rows[0]["ts"] == (close - timedelta(minutes=1)).replace(tzinfo=None)


# --- CLI ----------------------------------------------------------------------


def _jobs(session: Session) -> list[JobRun]:
    session.expire_all()
    return list(
        session.exec(
            select(JobRun)
            .where(col(JobRun.job).like("intraday-backfill-%"))
            .order_by(col(JobRun.id))
        ).all()
    )


def _cli(monkeypatch, engine, http: FakeHttp | None, **env: str) -> None:
    from stockviz import cli

    for name in ("ALPACA_KEY_ID", "ALPACA_SECRET_KEY", "TIINGO_API_KEY", "MASSIVE_API_KEY"):
        monkeypatch.setenv(name, env.get(name, ""))
    cli.get_settings.cache_clear()
    monkeypatch.setattr(cli, "engine", engine)
    real = registry.build_feed

    def build(name, settings, **options):
        clock = FakeClock()
        guard = http if http is not None else FakeHttp([])
        return real(name, settings, get=guard, clock=clock, sleep=clock.sleep, **options)

    monkeypatch.setattr(registry, "build_feed", build)


def _run(argv: list[str]) -> int:
    from stockviz import cli

    try:
        return cli.main(argv)
    finally:
        cli.get_settings.cache_clear()


ARGS = ["--symbols", "MSFT", "--from", "2025-03-03", "--to", "2025-03-03"]


@pytest.mark.parametrize("provider", ["alpaca", "tiingo", "massive"])
def test_exit_2_without_the_key_and_nothing_runs(
    provider: str, monkeypatch, engine, session: Session, capsys
) -> None:
    http = FakeHttp([])
    _cli(monkeypatch, engine, http, ALPACA_KEY_ID=KEY)  # half of Alpaca's pair
    assert _run(["intraday-backfill", "--provider", provider, *ARGS, "--apply"]) == 2
    assert http.calls == [] and _jobs(session) == []
    assert "not set" in capsys.readouterr().out


def test_dry_run_plans_without_fetching(monkeypatch, engine, session: Session, capsys) -> None:
    http = FakeHttp([])
    _cli(monkeypatch, engine, http, MASSIVE_API_KEY=KEY)
    assert _run(["intraday-backfill", "--provider", "massive", *ARGS]) == 0
    out = capsys.readouterr().out
    assert "calls: 1 per symbol" in out and "dry run" in out and KEY not in out
    assert http.calls == [] and _jobs(session) == []


def _stored(session: Session) -> list[IntradayBar]:
    session.expire_all()
    return list(session.exec(select(IntradayBar).order_by(col(IntradayBar.ts))).all())


def test_apply_writes_sip_minutes_idempotently_and_records_the_run(
    monkeypatch, engine, session: Session, capsys
) -> None:
    seed_symbols(session, "MSFT")

    def pages() -> list:
        return [
            response(200, fixture("massive_minutes_page1.json")),
            response(200, fixture("massive_minutes_page2.json")),
        ]

    http = FakeHttp(pages())
    _cli(monkeypatch, engine, http, MASSIVE_API_KEY=KEY)
    assert _run(["intraday-backfill", "--provider", "massive", *ARGS, "--apply"]) == 0
    rows = _stored(session)
    assert [r.ts for r in rows] == [datetime(2025, 3, 3, 14, 30), datetime(2025, 3, 3, 14, 31)]
    assert {(r.feed, r.interval, r.source) for r in rows} == {("sip", "1m", "massive")}
    assert rows[0].available_at == datetime(2025, 3, 3, 14, 31)
    assert rows[0].close == Decimal("390.8")
    out = capsys.readouterr().out
    assert "inserted 2" in out and KEY not in out

    http.queue.extend(pages())
    assert _run(["intraday-backfill", "--provider", "massive", *ARGS, "--apply"]) == 0
    assert len(_stored(session)) == 2
    assert "inserted 0, already stored 2" in capsys.readouterr().out
    jobs = _jobs(session)
    assert [(j.job, j.status, j.error) for j in jobs] == [
        (FEED_BACKFILL_JOBS["massive"], "succeeded", None)
    ] * 2


def test_auth_error_stops_and_keeps_a_fixed_summary(
    monkeypatch, engine, session: Session, capsys
) -> None:
    seed_symbols(session, "AAPL", "MSFT")
    http = FakeHttp([response(401, {"message": f"key {KEY} refused"})])
    _cli(monkeypatch, engine, http, ALPACA_KEY_ID=KEY, ALPACA_SECRET_KEY=SECRET)
    code = _run(
        ["intraday-backfill", "--provider", "alpaca", "--symbols", "AAPL", "MSFT", "NOPE",
         "--from", "2025-03-03", "--to", "2025-03-03", "--apply"]
    )  # fmt: skip
    assert code == 1
    out = capsys.readouterr().out
    assert "AAPL: failed" in out and "MSFT: skipped" in out and "stopped: auth" in out
    assert KEY not in out and SECRET not in out
    (job,) = _jobs(session)
    assert job.status == "failed" and job.error == "Alpaca: auth error on 1 symbol(s)"
    assert len(http.calls) == 1


def test_network_error_skips_one_symbol_and_unknown_symbols_are_listed(
    monkeypatch, engine, session: Session, capsys
) -> None:
    import httpx

    seed_symbols(session, "AAPL", "MSFT")
    http = FakeHttp([httpx.ConnectError("boom"), response(200, fixture("tiingo_iex_prices.json"))])
    _cli(monkeypatch, engine, http, TIINGO_API_KEY=KEY)
    code = _run(
        ["intraday-backfill", "--provider", "tiingo", "--symbols", "AAPL", "MSFT", "ZZZZ",
         "--from", "2025-03-03", "--to", "2025-03-03", "--apply"]
    )  # fmt: skip
    assert code == 1
    out = capsys.readouterr().out
    assert "AAPL: failed" in out and "MSFT: written" in out and "ZZZZ" in out
    assert {(r.feed, r.source) for r in _stored(session)} == {("iex", "tiingo_iex")}
    (job,) = _jobs(session)
    assert job.error == "Tiingo: network error on 1 symbol(s)"


def test_cli_refuses_indian_symbols_and_feed_misuse(monkeypatch, engine, capsys) -> None:
    _cli(monkeypatch, engine, None, ALPACA_KEY_ID=KEY, ALPACA_SECRET_KEY=SECRET, TIINGO_API_KEY=KEY)
    argv = ["--from", "2025-03-03", "--to", "2025-03-03"]
    assert _run(["intraday-backfill", "--provider", "alpaca", "--symbols", "TCS.NS", *argv]) == 1
    assert "US tickers only" in capsys.readouterr().out
    assert (
        _run(
            [
                "intraday-backfill",
                "--provider",
                "tiingo",
                "--symbols",
                "AAPL",
                "--feed",
                "sip",
                *argv,
            ]
        )
        == 1
    )
    bad = ["--from", "2025-03-04", "--to", "2025-03-03"]
    assert _run(["intraday-backfill", "--provider", "alpaca", "--symbols", "AAPL", *bad]) == 1


def test_backfill_is_not_in_the_cron_or_scheduler() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    assert "intraday-backfill" not in (root / ".railway" / "railway.ts").read_text()
    assert (
        "intraday-backfill"
        not in (root / "apps" / "api" / "src" / "stockviz" / "scheduler.py").read_text()
    )


# --- Feed status --------------------------------------------------------------


def _settings(**keys):
    from pydantic import SecretStr

    base = {
        "alpaca_key_id": "",
        "alpaca_secret_key": SecretStr(""),
        "tiingo_api_key": SecretStr(""),
        "massive_api_key": "",
        "finnhub_api_key": SecretStr(""),
    }
    base.update(keys)
    return get_settings().model_copy(update=base)


def test_feed_states(session: Session) -> None:
    from pydantic import SecretStr

    states = {s.provider: s.state for s in feed_statuses(session, _settings())}
    assert states == dict.fromkeys(("alpaca", "tiingo", "massive", "finnhub"), "not_configured")
    on = _settings(
        alpaca_key_id=KEY,
        alpaca_secret_key=SecretStr(SECRET),
        tiingo_api_key=SecretStr(KEY),
        massive_api_key=KEY,
        finnhub_api_key=SecretStr(KEY),
    )
    record_provider_run(session, FEED_BACKFILL_JOBS["alpaca"], ok=True)
    record_provider_run(
        session, FEED_BACKFILL_JOBS["tiingo"], ok=False, summary="Tiingo: rate error on 2 symbol(s)"
    )
    by = {s.provider: s for s in feed_statuses(session, on)}
    assert by["alpaca"].state == "ok" and by["alpaca"].last_success_at is not None
    assert by["tiingo"].state == "error"
    assert by["tiingo"].last_error == "Tiingo: rate error on 2 symbol(s)"
    assert by["massive"].state == "configured" and by["finnhub"].state == "configured"
    later = datetime.now(UTC).replace(tzinfo=None) + timedelta(days=4)
    assert {s.provider: s.state for s in feed_statuses(session, on, now=later)}["tiingo"] == (
        "configured"
    )


def _user(session: Session) -> int:
    user = User(email=f"{uuid4().hex}@stockviz.dev", name="Feeds")
    session.add(user)
    session.commit()
    session.refresh(user)
    assert user.id is not None
    return user.id


def test_feeds_route_never_returns_a_key(session: Session, client: TestClient, monkeypatch) -> None:
    from stockviz.main import app

    assert client.get("/v1/broker/feeds").status_code == 401
    on = _settings(alpaca_key_id=KEY, massive_api_key=KEY)
    app.dependency_overrides[get_settings] = lambda: on
    try:
        token = jose_jwt.encode(
            {"sub": str(_user(session))}, get_settings().internal_api_token, algorithm="HS256"
        )
        res = client.get("/v1/broker/feeds", headers={"Authorization": f"Bearer {token}"})
    finally:
        app.dependency_overrides.pop(get_settings, None)
    assert res.status_code == 200
    assert KEY not in res.text and SECRET not in res.text
    feeds = {f["provider"]: f for f in res.json()["feeds"]}
    assert feeds["alpaca"]["state"] == "not_configured"  # the secret half is blank
    assert feeds["massive"]["state"] == "configured"
    assert feeds["massive"]["capabilities"]["coverage"] == ["sip"]
    assert feeds["alpaca"]["key_env_vars"] == ["ALPACA_KEY_ID", "ALPACA_SECRET_KEY"]
    assert feeds["finnhub"]["capabilities"]["history"] is False


def test_status_and_health_leave_backfills_out(session: Session, client: TestClient) -> None:
    record_provider_run(session, FEED_BACKFILL_JOBS["massive"], ok=False, summary="x")
    assert FEED_BACKFILL_JOBS["massive"] not in {
        j["job"] for j in client.get("/v1/status").json()["jobs"]
    }
    health = client.get("/health").json()
    assert FEED_BACKFILL_JOBS["massive"] not in (health.get("failing_jobs") or [])
    assert session.exec(select(func.count()).select_from(JobRun)).one() == 1


# --- PostgreSQL: partitions and the multi-row insert ----------------------------

from tests.pg_scratch import postgres_admin_url, scratch_postgres_engine  # noqa: E402

needs_pg = pytest.mark.skipif(postgres_admin_url() is None, reason="DATABASE_URL is not PostgreSQL")


@needs_pg
def test_postgres_backfill_partitions_and_idempotency() -> None:
    from sqlalchemy import text

    with scratch_postgres_engine() as engine, Session(engine) as session:
        seed_symbols(session, "MSFT")
        plan = bf.make_plan(
            MassiveFeed(key=KEY), ["MSFT"], date(2025, 2, 28), date(2025, 3, 3), NOW
        )

        def pages() -> list:
            return [
                response(200, fixture("massive_minutes_page1.json")),
                response(200, fixture("massive_minutes_page2.json")),
            ]

        # One 30-day chunk covers 28 Feb to 3 Mar: one request plus its next page.
        first = bf.run_backfill(
            session, MassiveFeed(key=KEY, get=FakeHttp(pages())), plan, apply=True
        )
        assert [(r.status, r.inserted) for r in first.results] == [("written", 2)]
        again = bf.run_backfill(
            session, MassiveFeed(key=KEY, get=FakeHttp(pages())), plan, apply=True
        )
        assert [(r.inserted, r.already_stored) for r in again.results] == [(0, 2)]
        parts = (
            session.connection()
            .execute(
                text(
                    "SELECT relid::regclass::text FROM pg_partition_tree('intraday_bars') "
                    "WHERE isleaf ORDER BY 1"
                )
            )
            .scalars()
        )
        assert list(parts) == ["intraday_bars_y2025m03"]
