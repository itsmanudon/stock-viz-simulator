"""A10.2 (M12.1, M12.2): cohorts, assignments and the process-only gradebook."""

from __future__ import annotations

import json
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from stockviz.models import Drill
from stockviz.services import classroom as svc
from tests.test_drills import _auth, _seed, _user

DECK = {
    "rule": {"rule": "close crosses_above sma(close, 20)"},
    "universe": {"tickers": ["DRLX", "QZPM"]},
    "from": "2022-02-01",
    "to": "2023-06-30",
    "k": 2,
    "seed": 9,
}


def _setup(session: Session, client: TestClient) -> tuple[int, int, int, dict]:
    _seed(session, "DRLX", seed=1)
    _seed(session, "QZPM", seed=2)
    teacher = _user(session, "teacher@stockviz.dev")
    student = _user(session, "student@stockviz.dev")
    cohort = client.post("/v1/cohorts", json={"name": "Swing 101"}, headers=_auth(teacher))
    assert cohort.status_code == 201
    return teacher, student, cohort.json()["id"], cohort.json()


def test_join_needs_the_code_and_consent(session: Session, client: TestClient) -> None:
    teacher, student, _cid, cohort = _setup(session, client)
    code = cohort["invite_code"]
    assert len(code) == svc.CODE_LENGTH and not set(code) & set("01IO")
    h = _auth(student)
    no = client.post("/v1/cohorts/join", json={"code": code}, headers=h)
    assert no.status_code == 422 and "consent" in no.json()["detail"]
    assert (
        client.post(
            "/v1/cohorts/join", json={"code": "ZZZZZZZZ", "consent": True}, headers=h
        ).status_code
        == 404
    )
    ok = client.post("/v1/cohorts/join", json={"code": code.lower(), "consent": True}, headers=h)
    assert (
        ok.status_code == 200 and ok.json()["role"] == "member" and ok.json()["invite_code"] is None
    )
    assert "Never your P&L" in ok.json()["consent_text"]
    again = client.post("/v1/cohorts/join", json={"code": code, "consent": True}, headers=h)
    assert again.status_code == 409
    own = client.post(
        "/v1/cohorts/join", json={"code": code, "consent": True}, headers=_auth(teacher)
    )
    assert own.status_code == 409


def test_outsiders_and_members_cannot_see_what_they_should_not(
    session: Session, client: TestClient
) -> None:
    _teacher, student, cid, cohort = _setup(session, client)
    stranger = _user(session, "stranger@stockviz.dev")
    assert client.get(f"/v1/cohorts/{cid}", headers=_auth(stranger)).status_code == 404
    client.post(
        "/v1/cohorts/join",
        json={"code": cohort["invite_code"], "consent": True},
        headers=_auth(student),
    )
    assert client.get(f"/v1/cohorts/{cid}/gradebook", headers=_auth(student)).status_code == 404
    made = client.post(
        f"/v1/cohorts/{cid}/assignments", json={"title": "x", "deck": DECK}, headers=_auth(student)
    )
    assert made.status_code == 404


def _assignment(client: TestClient, teacher: int, cid: int, pct: int = 50) -> dict:
    res = client.post(
        f"/v1/cohorts/{cid}/assignments",
        json={"title": "Breakouts", "deck": {**DECK, "anonymised": False}, "min_followed_pct": pct},
        headers=_auth(teacher),
    )
    assert res.status_code == 201, res.text
    return res.json()


def test_every_student_drills_the_same_anonymised_triggers(
    session: Session, client: TestClient
) -> None:
    teacher, student, cid, cohort = _setup(session, client)
    other = _user(session, "other@stockviz.dev")
    for uid in (student, other):
        client.post(
            "/v1/cohorts/join",
            json={"code": cohort["invite_code"], "consent": True},
            headers=_auth(uid),
        )
    a = _assignment(client, teacher, cid)
    assert a["seed"] == 9 and a["k"] == 2
    first = client.post(f"/v1/assignments/{a['id']}/start", headers=_auth(student)).json()
    again = client.post(f"/v1/assignments/{a['id']}/start", headers=_auth(student)).json()
    assert first["created"] and not again["created"] and first["deck_id"] == again["deck_id"]
    second = client.post(f"/v1/assignments/{a['id']}/start", headers=_auth(other)).json()

    def triggers(deck_id: int) -> list[tuple[str, str]]:
        rows = session.exec(select(Drill).where(Drill.deck_id == deck_id)).all()
        return [
            (d.ticker, d.trigger_date.isoformat()) for d in sorted(rows, key=lambda d: d.position)
        ]

    assert triggers(first["deck_id"]) == triggers(second["deck_id"])
    deck = client.get(f"/v1/drills/decks/{first['deck_id']}", headers=_auth(student)).json()
    assert deck["anonymised"] is True  # forced, though the teacher sent false
    stranger = _user(session, "late@stockviz.dev")
    assert (
        client.post(f"/v1/assignments/{a['id']}/start", headers=_auth(stranger)).status_code == 404
    )
    mine = client.get(f"/v1/cohorts/{cid}", headers=_auth(student)).json()
    assert mine["assignments"][0]["my_deck_id"] == first["deck_id"]


def _play(client: TestClient, uid: int, deck_id: int, *, follow: bool) -> None:
    """Plan, trade and reveal every drill; follow the plan or break its size."""
    h = _auth(uid)
    deck = client.get(f"/v1/drills/decks/{deck_id}", headers=h).json()
    for row in deck["drills"]:
        did = row["id"]
        close = Decimal(client.get(f"/v1/drills/{did}", headers=h).json()["bar"]["close"])
        client.put(f"/v1/drills/{did}/plan", headers=h,
                   json={"planned_entry": str(close), "planned_stop": str(close - 1), "planned_size": "3"})  # fmt: skip
        qty = "3" if follow else "9"
        client.post(f"/v1/drills/{did}/orders", headers=h, json={"side": "buy", "quantity": qty})
        assert client.post(f"/v1/drills/{did}/reveal", headers=h).status_code == 200


def test_the_gradebook_shows_process_only_and_grades_by_the_rubric(
    session: Session, client: TestClient
) -> None:
    teacher, student, cid, cohort = _setup(session, client)
    sloppy = _user(session, "sloppy@stockviz.dev")
    idle = _user(session, "idle@stockviz.dev")
    for uid in (student, sloppy, idle):
        client.post(
            "/v1/cohorts/join",
            json={"code": cohort["invite_code"], "consent": True},
            headers=_auth(uid),
        )
    a = _assignment(client, teacher, cid, pct=50)
    for uid, follow in ((student, True), (sloppy, False)):
        deck_id = client.post(f"/v1/assignments/{a['id']}/start", headers=_auth(uid)).json()[
            "deck_id"
        ]
        _play(client, uid, deck_id, follow=follow)

    book = client.get(f"/v1/cohorts/{cid}/gradebook", headers=_auth(teacher))
    assert book.status_code == 200
    body = book.json()
    grades = {r["user_id"]: r["cells"][0] for r in body["rows"]}
    assert grades[student]["grade"] == "meets_rubric" and grades[student]["followed_pct"] == 100
    assert grades[sloppy]["grade"] == "below_rubric" and grades[sloppy]["followed_plan"] == 0
    assert grades[idle]["grade"] == "not_started" and not grades[idle]["started"]
    # Nothing that could carry money, R, fills, symbols or dates reaches the instructor.
    text = json.dumps(body["rows"]).lower()
    for banned in (
        "pnl",
        "r_achieved",
        "fill",
        "price",
        "drlx",
        "qzpm",
        "ticker",
        "2022-",
        "2023-",
    ):
        assert banned not in text, banned
    assert "P&L, R, fills" in body["privacy"]


def test_leaving_removes_the_student_from_the_gradebook(
    session: Session, client: TestClient
) -> None:
    teacher, student, cid, cohort = _setup(session, client)
    client.post(
        "/v1/cohorts/join",
        json={"code": cohort["invite_code"], "consent": True},
        headers=_auth(student),
    )
    a = _assignment(client, teacher, cid)
    deck_id = client.post(f"/v1/assignments/{a['id']}/start", headers=_auth(student)).json()[
        "deck_id"
    ]
    assert client.delete(f"/v1/cohorts/{cid}/membership", headers=_auth(student)).status_code == 204
    assert client.get(f"/v1/cohorts/{cid}/gradebook", headers=_auth(teacher)).json()["rows"] == []
    # The deck is still the student's.
    assert client.get(f"/v1/drills/decks/{deck_id}", headers=_auth(student)).status_code == 200
    assert client.get(f"/v1/cohorts/{cid}", headers=_auth(student)).status_code == 404


@pytest.mark.parametrize(
    ("counts", "grade"),
    [
        ({"drills": 2, "revealed": 1, "traded": 1, "followed_plan": 1}, "in_progress"),
        ({"drills": 2, "revealed": 2, "traded": 2, "followed_plan": 1}, "meets_rubric"),
        ({"drills": 2, "revealed": 2, "traded": 2, "followed_plan": 0}, "below_rubric"),
        ({"drills": 2, "revealed": 2, "traded": 0, "followed_plan": 0}, "below_rubric"),
    ],
)
def test_rubric(counts: dict[str, int], grade: str) -> None:
    assert svc.grade(counts, 50)[1] == grade
