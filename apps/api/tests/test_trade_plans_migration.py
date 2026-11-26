"""A5.4's migration (``b5d4a7e1c902``) on PostgreSQL: up, down, up, with data.

Drills and replay sessions are played through the API at head. The
downgrade writes their plans back into ``drill_plans`` and
``replay_journals`` (the A4.7 / SIM-07 tables); old-style rows are then
added by hand the way the old code left them (a journal started after the
first fill, a drill plan whose lock was never caught up). Each drill's
process score is computed from the old tables with the A4.7 recipe, and must
equal what the drill route returns after the upgrade copies them into
``trade_plans``; replay forensics must be identical before and after; the
archived tables keep their rows in the ``archive`` schema.
"""

from __future__ import annotations

import importlib.util
import logging
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import inspect, text
from sqlmodel import Session

from stockviz.db import get_session
from stockviz.main import app
from stockviz.models import ReplaySession
from stockviz.services.drills.score import BarFacts, FillFacts, PlanFacts, score_drill
from stockviz.services.replay import (
    compute_replay_summary,
    get_visible_replay_history,
    list_replay_fills,
)
from stockviz.settings import get_settings
from tests.pg_scratch import postgres_admin_url, scratch_alembic_engine
from tests.test_drills import RULE, _auth, _seed, _user

pytestmark = pytest.mark.skipif(
    postgres_admin_url() is None, reason="DATABASE_URL is not PostgreSQL"
)

API_ROOT = Path(__file__).resolve().parents[1]
BEFORE = "6ad74b7c4b5b"


@pytest.fixture(autouse=True)
def _keep_logging() -> Iterator[None]:
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    disabled = {
        name: lg.disabled
        for name, lg in logging.root.manager.loggerDict.items()
        if isinstance(lg, logging.Logger)
    }
    yield
    root.handlers[:] = handlers
    root.setLevel(level)
    for name, lg in logging.root.manager.loggerDict.items():
        if isinstance(lg, logging.Logger):
            lg.disabled = disabled.get(name, False)


def _migration() -> Any:
    path = API_ROOT / "migrations" / "versions" / "b5d4a7e1c902_a5_4_trade_plans.py"
    spec = importlib.util.spec_from_file_location("a54_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _client(session: Session) -> TestClient:
    def _override() -> Iterator[Session]:
        yield session

    app.dependency_overrides[get_session] = _override
    return TestClient(app)


def _old_score(session: Session, sid: int) -> dict[str, Any] | None:
    """A4.7's ``score_of``, reading ``drill_plans`` (the old revision)."""
    row = session.execute(
        text(
            "SELECT planned_entry, planned_stop, planned_size FROM drill_plans WHERE session_id = :s"
        ),
        {"s": sid},
    ).first()
    if row is None:
        return None
    replay = session.get(ReplaySession, sid)
    assert replay is not None
    fills = [
        FillFacts(f.side, f.quantity, f.fill_price, f.evaluated_at)
        for f in list_replay_fills(session, replay=replay)
    ]
    bars = [BarFacts(b.ts, b.close) for b in get_visible_replay_history(session, replay)]
    summary = compute_replay_summary(session, replay)
    return score_drill(
        PlanFacts(Decimal(row[0]), Decimal(row[1]), Decimal(row[2])),
        fills,
        bars,
        total_pnl=summary.total_pnl,
    ).model_dump(mode="json")


def test_a54_trade_plans_migration_keeps_drill_scores_and_forensics(monkeypatch) -> None:
    with scratch_alembic_engine() as engine:
        monkeypatch.setenv("DATABASE_URL", engine.url.render_as_string(hide_password=False))
        get_settings.cache_clear()
        config = Config(str(API_ROOT / "alembic.ini"))
        config.set_main_option("script_location", str(API_ROOT / "migrations"))
        try:
            command.upgrade(config, "head")
            tables = set(inspect(engine).get_table_names())
            assert "trade_plans" in tables and not {"drill_plans", "replay_journals"} & tables

            # --- play drills and replays through the API at head -------------
            with Session(engine) as session:
                _seed(session, "DRLX", seed=1)
                _seed(session, "QZPM", seed=2)
                uid = _user(session, "a54-mig@stockviz.dev")
                h = _auth(uid)
                client = _client(session)
                deck = client.post(
                    "/v1/drills/decks",
                    json={"rule": {"rule": RULE}, "universe": {"tickers": ["DRLX", "QZPM"]},
                          "k": 3, "seed": 5, "from": "2022-02-01", "to": "2023-06-30"},
                    headers=h,
                ).json()  # fmt: skip
                drills = [d["id"] for d in deck["drills"]]
                for n, did in enumerate(drills[:2]):
                    close = Decimal(
                        client.get(f"/v1/drills/{did}", headers=h).json()["bar"]["close"]
                    )
                    ok = client.put(f"/v1/drills/{did}/plan", headers=h, json={
                        "planned_entry": str(close), "planned_stop": str(close - 2),
                        "planned_size": "3", "note": f"drill {n}"})  # fmt: skip
                    assert ok.status_code == 200, ok.text
                    client.post(f"/v1/drills/{did}/orders", headers=h,
                                json={"side": "buy", "quantity": str(3 + n)})  # fmt: skip
                    for _ in range(4):
                        client.post(f"/v1/drills/{did}/advance", headers=h)
                    if n == 1:
                        client.post(f"/v1/drills/{did}/orders", headers=h,
                                    json={"side": "sell", "quantity": "4"})  # fmt: skip
                    assert client.post(f"/v1/drills/{did}/reveal", headers=h).status_code == 200
                assert client.post(f"/v1/drills/{drills[2]}/reveal", headers=h).status_code == 200

                # Replay A: journal written before the first buy (locks at it).
                ra = client.post("/v1/replay/sessions", headers=h,
                                 json={"ticker": "DRLX", "start_at": "2022-06-01T00:00:00"}).json()["id"]  # fmt: skip
                put = client.put(f"/v1/replay/sessions/{ra}/journal", headers=h,
                                 json={"thesis": "Base breakout", "confidence": 4,
                                       "expected_holding_bars": 10})  # fmt: skip
                assert put.status_code == 200 and not put.json()["locked"]
                client.post(
                    f"/v1/replay/sessions/{ra}/orders",
                    headers=h,
                    json={"side": "buy", "quantity": "5"},
                )
                for _ in range(5):
                    client.post(f"/v1/replay/sessions/{ra}/advance", headers=h)
                client.post(
                    f"/v1/replay/sessions/{ra}/orders",
                    headers=h,
                    json={"side": "sell", "quantity": "2"},
                )
                client.put(f"/v1/replay/sessions/{ra}/journal", headers=h,
                           json={"thesis": "Base breakout", "confidence": 4,
                                 "expected_holding_bars": 10, "reflection": "Sold early"})  # fmt: skip
                # Replay B: traded with no journal (one is added the old way below).
                rb = client.post("/v1/replay/sessions", headers=h,
                                 json={"ticker": "QZPM", "start_at": "2022-08-01T00:00:00"}).json()["id"]  # fmt: skip
                client.post(
                    f"/v1/replay/sessions/{rb}/orders",
                    headers=h,
                    json={"side": "buy", "quantity": "7"},
                )
                for _ in range(3):
                    client.post(f"/v1/replay/sessions/{rb}/advance", headers=h)

                def snapshot() -> dict[str, Any]:
                    out: dict[str, Any] = {"drills": {}, "forensics": {}}
                    for did in drills:
                        view = client.get(f"/v1/drills/{did}", headers=h).json()
                        out["drills"][did] = {"score": view["score"], "plan": view["plan"]}
                    out["deck"] = client.get(f"/v1/drills/decks/{deck['id']}", headers=h).json()[
                        "summary"
                    ]
                    for sid in (ra, rb):
                        out["forensics"][sid] = client.get(
                            f"/v1/replay/sessions/{sid}/forensics", headers=h
                        ).json()
                    return out

                before = snapshot()
                assert all(before["drills"][d]["score"]["traded"] for d in drills[:2])
                assert before["drills"][drills[2]]["score"] is None
                assert all(f["fills_count"] > 0 for f in before["forensics"].values())
                journal_a = client.get(f"/v1/replay/sessions/{ra}/journal", headers=h).json()
                assert journal_a["locked"] and not journal_a["written_after_entry"]
                drill_sids = [
                    session.execute(
                        text("SELECT session_id FROM drills WHERE id = :d"), {"d": d}
                    ).scalar_one()
                    for d in drills
                ]
                session.close()
            app.dependency_overrides.clear()

            # --- down: the plans go back into the old tables ------------------
            command.downgrade(config, BEFORE)
            tables = set(inspect(engine).get_table_names())
            assert {"drill_plans", "replay_journals"} <= tables and "trade_plans" not in tables
            with Session(engine) as session:
                counts = session.execute(
                    text(
                        "SELECT (SELECT count(*) FROM drill_plans), (SELECT count(*) FROM replay_journals)"
                    )
                ).one()
                assert tuple(counts) == (2, 1)  # two drill plans; replay A's journal
                # Old-style rows: replay B's journal started after its fill,
                # and drill 0's lock never caught up.
                session.execute(
                    text("INSERT INTO replay_journals (session_id, thesis, confidence, created_at, "
                         "updated_at) VALUES (:s, 'Late note', 2, now(), now())"),
                    {"s": rb},
                )  # fmt: skip
                session.execute(
                    text("UPDATE drill_plans SET locked_at = NULL WHERE session_id = :s"),
                    {"s": drill_sids[0]},
                )
                session.commit()
                old_scores = {
                    d: _old_score(session, s) for d, s in zip(drills, drill_sids, strict=True)
                }
                old_forensics_rows = session.execute(
                    text("SELECT count(*) FROM replay_fills WHERE session_id IN (:a, :b)"),
                    {"a": ra, "b": rb},
                ).scalar_one()
            for did in drills:
                assert old_scores[did] == before["drills"][did]["score"]
            assert old_scores[drills[2]] is None  # no plan, no score

            # --- up again: the copy into trade_plans --------------------------
            command.upgrade(config, "head")
            tables = set(inspect(engine).get_table_names())
            assert "trade_plans" in tables and not {"drill_plans", "replay_journals"} & tables
            archived = set(inspect(engine).get_table_names(schema="archive"))
            assert {"drill_plans", "replay_journals"} <= archived
            with Session(engine) as session:
                assert (
                    session.execute(text("SELECT count(*) FROM archive.drill_plans")).scalar_one()
                    == 2
                )
                assert (
                    session.execute(
                        text("SELECT count(*) FROM archive.replay_journals")
                    ).scalar_one()
                    == 2
                )
                rows = session.execute(
                    text("SELECT replay_session_id, source, status, locked_at, first_fill_at, "
                         "written_after_entry FROM trade_plans ORDER BY replay_session_id")
                ).all()  # fmt: skip
                assert len(rows) == 4  # two drills, two replays
                by_sid = {r[0]: r for r in rows}
                assert by_sid[drill_sids[0]][1] == "drill" and by_sid[ra][1] == "replay"
                assert by_sid[drill_sids[0]][3] == by_sid[drill_sids[0]][4]  # caught up at the fill
                assert by_sid[rb][5] is True and by_sid[rb][3] is None  # written after entry
                assert by_sid[ra][5] is False and by_sid[ra][3] is not None
                # Idempotent copy: a second run adds nothing.
                session.execute(text("SET LOCAL search_path TO archive, public"))
                session.execute(text(_migration().COPY))
                assert session.execute(text("SELECT count(*) FROM trade_plans")).scalar_one() == 4
                session.rollback()

                client = _client(session)
                after: dict[str, Any] = {"drills": {}, "forensics": {}}
                for did in drills:
                    view = client.get(f"/v1/drills/{did}", headers=h).json()
                    after["drills"][did] = {"score": view["score"], "plan": view["plan"]}
                after["deck"] = client.get(f"/v1/drills/decks/{deck['id']}", headers=h).json()[
                    "summary"
                ]
                for sid in (ra, rb):
                    after["forensics"][sid] = client.get(
                        f"/v1/replay/sessions/{sid}/forensics", headers=h
                    ).json()
                assert after["drills"] == before["drills"]
                assert after["deck"] == before["deck"]
                assert after["forensics"] == before["forensics"]
                assert old_forensics_rows == sum(
                    f["fills_count"] for f in after["forensics"].values()
                )
                ja = client.get(f"/v1/replay/sessions/{ra}/journal", headers=h).json()
                assert ja == journal_a
                jb = client.get(f"/v1/replay/sessions/{rb}/journal", headers=h).json()
                assert jb["thesis"] == "Late note" and jb["locked"] and jb["written_after_entry"]
                assert client.put(f"/v1/replay/sessions/{rb}/journal", headers=h,
                                  json={"thesis": "Changed", "confidence": 2}).status_code == 409  # fmt: skip
                session.close()
            app.dependency_overrides.clear()

            # A paper plan blocks the downgrade (nothing would keep it).
            with Session(engine) as session:
                client = _client(session)
                made = client.post("/v1/plans", headers=h, json={
                    "ticker": "DRLX", "planned_entry": "10", "planned_stop": "9",
                    "planned_size": "1"})  # fmt: skip
                assert made.status_code == 201, made.text
                session.close()
            app.dependency_overrides.clear()
            with pytest.raises(RuntimeError, match="1 paper or imported trade plans"):
                command.downgrade(config, BEFORE)
        finally:
            app.dependency_overrides.clear()
            engine.dispose()
            get_settings.cache_clear()
