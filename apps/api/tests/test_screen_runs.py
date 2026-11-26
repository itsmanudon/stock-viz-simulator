"""A2.3: nightly screen runs and their entry/exit notifications."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from fastapi.testclient import TestClient
from jose import jwt as jose_jwt
from sqlmodel import Session, select

from stockviz import cli
from stockviz.models import Notification, PriceBar, SavedScreen, ScreenRun, User
from stockviz.services.dsl import compile_rule
from stockviz.services.instruments import instrument_ids
from stockviz.services.screen_runs import run_screen_runs
from stockviz.services.setups import store
from stockviz.settings import get_settings
from tests.symbols import seed_symbols

MONDAY = datetime(2026, 11, 9)
TUESDAY = datetime(2026, 11, 10)
MONDAY_NIGHT = datetime(2026, 11, 9, 22, 0)
TUESDAY_NIGHT = datetime(2026, 11, 10, 22, 0)
SECRET = get_settings().internal_api_token


def _auth(user_id: int) -> dict[str, str]:
    return {
        "Authorization": "Bearer "
        + jose_jwt.encode({"sub": str(user_id)}, SECRET, algorithm="HS256")
    }


def _bar(session: Session, ticker: str, ts: datetime, close: float) -> None:
    c = Decimal(str(close))
    session.add(
        PriceBar(
            ticker=ticker, ts=ts, interval="1d",
            open=c, high=c, low=c, close=c, volume=1000, source="test",
        )
    )  # fmt: skip
    session.commit()


def _world(session: Session, *, notify: bool = True, query: str = "") -> tuple[int, int, int]:
    """Two users' screens on one rule; returns (user, screen id, version id)."""
    seed_symbols(session, "AAA", "BBB", "CCC")
    user = User(email="screens@stockviz.dev", name="Screens")
    session.add(user)
    session.commit()
    assert user.id is not None
    _setup, version = store.create_setup(
        session, user.id, name="Over 100", kind="screen", rule=compile_rule("close > 100")
    )
    screen = SavedScreen(
        user_id=user.id,
        name="Hundreds",
        query=query,
        setup_version_id=version.id,
        notify_on_change=notify,
    )
    session.add(screen)
    session.commit()
    assert screen.id is not None and version.id is not None
    _bar(session, "AAA", MONDAY, 105)  # member
    _bar(session, "BBB", MONDAY, 90)
    _bar(session, "CCC", MONDAY, 120)  # member
    return user.id, screen.id, version.id


def _tuesday(session: Session) -> None:
    _bar(session, "AAA", TUESDAY, 95)  # exits
    _bar(session, "BBB", TUESDAY, 110)  # enters
    _bar(session, "CCC", TUESDAY, 121)  # stays


def _notes(session: Session) -> list[Notification]:
    return list(session.exec(select(Notification).order_by(Notification.id)).all())  # type: ignore[arg-type]


def test_first_run_records_state_only(session: Session) -> None:
    _user, _screen, version = _world(session)
    result = run_screen_runs(session, now=MONDAY_NIGHT)
    assert result.runs == 1 and result.notifications == 0
    run = session.exec(select(ScreenRun)).one()
    ids = instrument_ids(session, ["AAA", "CCC"])
    assert run.setup_version_id == version and run.session_date == MONDAY.date()
    assert sorted(run.members) == sorted(ids.values())
    assert run.evaluated == 3 and run.not_evaluated == 0 and run.venue == "all"
    assert run.sessions == {"XNYS": "2026-11-09"}
    assert _notes(session) == []


def test_entries_and_exits_become_one_notification(session: Session) -> None:
    user, screen, _version = _world(session)
    run_screen_runs(session, now=MONDAY_NIGHT)
    _tuesday(session)
    result = run_screen_runs(session, now=TUESDAY_NIGHT)
    assert result.notifications == 1
    (note,) = _notes(session)
    assert note.user_id == user and note.category == "screen"
    assert note.source_key == f"{screen}:2026-11-10"
    assert note.data is not None
    assert note.data["entries"] == ["BBB"] and note.data["exits"] == ["AAA"]
    assert "1 in, 1 out" in note.title
    assert "Entered (1): BBB" in note.body and "Left (1): AAA" in note.body


def test_a_rerun_replaces_the_day_and_notifies_nothing_new(session: Session) -> None:
    _world(session)
    run_screen_runs(session, now=MONDAY_NIGHT)
    _tuesday(session)
    run_screen_runs(session, now=TUESDAY_NIGHT)
    again = run_screen_runs(session, now=TUESDAY_NIGHT)
    assert again.runs == 1 and again.notifications == 0
    runs = session.exec(select(ScreenRun).order_by(ScreenRun.session_date)).all()  # type: ignore[arg-type]
    assert [r.session_date for r in runs] == [MONDAY.date(), TUESDAY.date()]
    assert len(_notes(session)) == 1


def test_no_notification_when_the_flag_is_off(session: Session) -> None:
    _world(session, notify=False)
    run_screen_runs(session, now=MONDAY_NIGHT)
    _tuesday(session)
    result = run_screen_runs(session, now=TUESDAY_NIGHT)
    assert result.runs == 1 and result.notifications == 0
    assert _notes(session) == []


def test_the_screen_currency_filter_limits_the_diff(session: Session) -> None:
    _world(session, query="currency=INR")
    run_screen_runs(session, now=MONDAY_NIGHT)
    _tuesday(session)
    assert run_screen_runs(session, now=TUESDAY_NIGHT).notifications == 0


def test_unknown_results_are_counted_not_members(session: Session) -> None:
    _world(session)
    run_screen_runs(session, now=MONDAY_NIGHT)
    _bar(session, "AAA", TUESDAY, 99)
    _bar(session, "BBB", TUESDAY, 101)
    # CCC has no Tuesday bar: unknown, so it neither stays nor "exits".
    run_screen_runs(session, now=TUESDAY_NIGHT)
    run = session.exec(select(ScreenRun).where(ScreenRun.session_date == TUESDAY.date())).one()
    assert run.not_evaluated == 1
    (note,) = _notes(session)
    assert note.data is not None
    assert note.data["exits"] == ["AAA", "CCC"]  # CCC was a member and is not now


def test_the_cli_job_runs_and_is_recorded(session: Session, engine, monkeypatch) -> None:
    _world(session)
    monkeypatch.setattr(cli, "engine", engine)
    monkeypatch.setattr("stockviz._time.utcnow", lambda: MONDAY_NIGHT)
    assert "screen-runs" in cli.RECORDED_JOBS
    assert cli.main(["screen-runs"]) == 0


# --- /v1/screens notify_on_change --------------------------------------------


def test_the_notify_toggle(session: Session, client: TestClient) -> None:
    user, screen, version = _world(session, notify=False)
    h = _auth(user)
    r = client.patch(f"/v1/screens/{screen}", headers=h, json={"notify_on_change": True})
    assert r.status_code == 200 and r.json()["notify_on_change"] is True
    # Saving by name without the field keeps it.
    saved = client.post(
        "/v1/screens",
        headers=h,
        json={"name": "Hundreds", "query": "sort=ticker", "setup_version_id": version},
    ).json()
    assert saved["notify_on_change"] is True
    # A screen with no rule cannot subscribe.
    plain = client.post("/v1/screens", headers=h, json={"name": "Plain", "query": ""}).json()
    assert plain["notify_on_change"] is False
    bad = client.patch(f"/v1/screens/{plain['id']}", headers=h, json={"notify_on_change": True})
    assert bad.status_code == 400
    assert (
        client.post(
            "/v1/screens",
            headers=h,
            json={"name": "Plain2", "query": "", "notify_on_change": True},
        ).status_code
        == 400
    )
    other = User(email="nosy@stockviz.dev", name="Nosy")
    session.add(other)
    session.commit()
    assert other.id is not None
    assert (
        client.patch(
            f"/v1/screens/{screen}", headers=_auth(other.id), json={"notify_on_change": False}
        ).status_code
        == 404
    )
