"""A2.2: rule check, setups and their immutable versions, presets, forks."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from jose import jwt as jose_jwt
from sqlmodel import Session, col, select

from stockviz.models import User
from stockviz.models.setup import Setup, SetupVersion
from stockviz.services.setups.presets import PRESETS, seed_presets
from stockviz.settings import get_settings

SECRET = get_settings().internal_api_token


def _auth(user_id: int) -> dict[str, str]:
    token = jose_jwt.encode({"sub": str(user_id)}, SECRET, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


def _user(session: Session, email: str) -> int:
    user = User(email=email, name=email.split("@")[0])
    session.add(user)
    session.commit()
    session.refresh(user)
    assert user.id is not None
    return user.id


# --- POST /v1/rules/check ---------------------------------------------------


def test_rule_check_valid(client: TestClient) -> None:
    body = client.post(
        "/v1/rules/check", json={"rule": "rsi() < 30 and close > sma(close, n=200)"}
    ).json()
    assert body["valid"] is True
    assert body["canonical"] == "close > sma(close, 200) and rsi(14) < 30"
    assert len(body["hash"]) == 64
    assert body["type"] == "boolean series"
    assert body["warmup_bars"] == 199 and body["warmup_whole_history"] is False
    assert body["error"] is None


def test_rule_check_same_rule_same_hash(client: TestClient) -> None:
    a = client.post("/v1/rules/check", json={"rule": "rsi() < 30 and close > sma(close, 200)"})
    b = client.post("/v1/rules/check", json={"rule": "close > sma(close, n=200) and rsi(14)<30"})
    assert a.json()["hash"] == b.json()["hash"]


def test_rule_check_uses_and_whole_history(client: TestClient) -> None:
    body = client.post(
        "/v1/rules/check",
        json={"rule": "bars_since(close > open) < 3 and fundamental.pe < 20 and rs(63) > 0"},
    ).json()
    assert body["valid"] and body["warmup_bars"] is None and body["warmup_whole_history"]
    assert body["uses"] == ["benchmark", "fundamentals"]


@pytest.mark.parametrize(
    ("rule", "kind", "column"),
    [
        ("close > sma(close, 200) andd rsi(14) < 30", "syntax", 25),
        ("close + 1", "type", 1),
        ("close > foo(3)", "type", 9),
    ],
)
def test_rule_check_errors_carry_line_and_column(
    client: TestClient, rule: str, kind: str, column: int
) -> None:
    res = client.post("/v1/rules/check", json={"rule": rule})
    assert res.status_code == 200
    body = res.json()
    assert body["valid"] is False and body["canonical"] is None
    assert body["error"]["kind"] == kind
    assert body["error"]["line"] == 1 and body["error"]["column"] == column
    assert body["error"]["message"]


def test_rule_check_refuses_empty_and_huge(client: TestClient) -> None:
    assert client.post("/v1/rules/check", json={"rule": ""}).status_code == 422
    assert client.post("/v1/rules/check", json={"rule": "x" * 4001}).status_code == 422


# --- /v1/setups ---------------------------------------------------------------


def test_setups_require_auth(client: TestClient) -> None:
    assert client.get("/v1/setups").status_code == 401
    assert client.post("/v1/setups", json={}).status_code == 401
    assert client.post("/v1/setups/1/fork").status_code == 401


def test_create_get_and_list(session: Session, client: TestClient) -> None:
    uid = _user(session, "a@x.dev")
    res = client.post(
        "/v1/setups",
        json={"name": "Trend", "kind": "screen", "rule": "close > sma(close, 200)", "notes": "v1"},
        headers=_auth(uid),
    )
    assert res.status_code == 201
    body = res.json()
    assert body["owned"] and not body["is_preset"] and body["version_count"] == 1
    assert body["versions"][0]["version"] == 1
    assert body["latest_version"]["canonical_text"] == "close > sma(close, 200)"
    assert body["latest_version"]["notes"] == "v1"

    got = client.get(f"/v1/setups/{body['id']}", headers=_auth(uid)).json()
    assert got["versions"] == body["versions"]
    listed = client.get("/v1/setups", headers=_auth(uid)).json()
    assert [s["id"] for s in listed] == [body["id"]]


def test_create_refuses_a_rule_that_does_not_compile(session: Session, client: TestClient) -> None:
    uid = _user(session, "a@x.dev")
    res = client.post(
        "/v1/setups", json={"name": "Bad", "rule": "close >"}, headers=_auth(uid)
    )
    assert res.status_code == 422
    assert res.json()["detail"]["kind"] == "syntax"
    assert res.json()["detail"]["column"] is not None
    assert session.exec(select(Setup)).all() == []


def test_versions_are_immutable_and_same_rule_is_same_version(
    session: Session, client: TestClient
) -> None:
    uid = _user(session, "a@x.dev")
    sid = client.post(
        "/v1/setups", json={"name": "T", "rule": "rsi(14) < 30"}, headers=_auth(uid)
    ).json()["id"]
    first = client.get(f"/v1/setups/{sid}", headers=_auth(uid)).json()["versions"][0]

    new = client.post(
        f"/v1/setups/{sid}/versions", json={"rule": "rsi(14) < 25"}, headers=_auth(uid)
    )
    assert new.status_code == 201 and new.json()["version"] == 2

    # The same rule written differently is the same version: 200, nothing added.
    again = client.post(
        f"/v1/setups/{sid}/versions", json={"rule": "rsi() < 30  # spacing"}, headers=_auth(uid)
    )
    assert again.status_code == 200
    assert again.json()["id"] == first["id"] and again.json()["version"] == 1

    detail = client.get(f"/v1/setups/{sid}", headers=_auth(uid)).json()
    assert [v["version"] for v in detail["versions"]] == [2, 1]
    # Version 1 is exactly as it was.
    assert detail["versions"][1] == first
    assert detail["latest_version"]["rule_text"] == "rsi(14) < 25"
    # No route updates a version.
    assert client.put(f"/v1/setups/{sid}/versions/{first['id']}", json={}).status_code in (
        404,
        405,
    )


def test_other_users_setup_is_not_found(session: Session, client: TestClient) -> None:
    a, b = _user(session, "a@x.dev"), _user(session, "b@x.dev")
    sid = client.post(
        "/v1/setups", json={"name": "Mine", "rule": "close > open"}, headers=_auth(a)
    ).json()["id"]
    assert client.get(f"/v1/setups/{sid}", headers=_auth(b)).status_code == 404
    assert (
        client.post(
            f"/v1/setups/{sid}/versions", json={"rule": "close < open"}, headers=_auth(b)
        ).status_code
        == 404
    )
    assert client.post(f"/v1/setups/{sid}/fork", headers=_auth(b)).status_code == 404
    assert client.get("/v1/setups", headers=_auth(b)).json() == []


def test_archive_hides_and_blocks_new_versions(session: Session, client: TestClient) -> None:
    uid = _user(session, "a@x.dev")
    sid = client.post(
        "/v1/setups", json={"name": "Old", "rule": "close > open"}, headers=_auth(uid)
    ).json()["id"]
    archived = client.post(f"/v1/setups/{sid}/archive", headers=_auth(uid)).json()
    assert archived["archived_at"] is not None
    assert client.get("/v1/setups", headers=_auth(uid)).json() == []
    with_archived = client.get("/v1/setups?include_archived=true", headers=_auth(uid)).json()
    assert [s["id"] for s in with_archived] == [sid]
    res = client.post(
        f"/v1/setups/{sid}/versions", json={"rule": "close < open"}, headers=_auth(uid)
    )
    assert res.status_code == 409


def test_presets_are_listed_read_only_and_forkable(session: Session, client: TestClient) -> None:
    seed_presets(session)
    uid = _user(session, "a@x.dev")
    listed = client.get("/v1/setups", headers=_auth(uid)).json()
    presets = [s for s in listed if s["is_preset"]]
    assert {s["name"] for s in presets} == {p.name for p in PRESETS}
    assert all(not s["owned"] for s in presets)
    preset = presets[0]
    pid = preset["id"]

    assert (
        client.post(
            f"/v1/setups/{pid}/versions", json={"rule": "close > open"}, headers=_auth(uid)
        ).status_code
        == 403
    )
    assert client.post(f"/v1/setups/{pid}/archive", headers=_auth(uid)).status_code == 403

    forked = client.post(f"/v1/setups/{pid}/fork", json={}, headers=_auth(uid))
    assert forked.status_code == 201
    body = forked.json()
    assert body["owned"] and not body["is_preset"] and body["name"].endswith("(fork)")
    assert body["forked_from_version_id"] == preset["latest_version"]["id"]
    assert body["latest_version"]["rule_hash"] == preset["latest_version"]["rule_hash"]
    assert body["description"] == preset["description"]
    # The fork is the user's to change.
    res = client.post(
        f"/v1/setups/{body['id']}/versions", json={"rule": "close > open"}, headers=_auth(uid)
    )
    assert res.status_code == 201


def test_fork_a_chosen_version_with_a_name(session: Session, client: TestClient) -> None:
    uid = _user(session, "a@x.dev")
    sid = client.post(
        "/v1/setups", json={"name": "S", "rule": "close > open"}, headers=_auth(uid)
    ).json()["id"]
    v1 = client.get(f"/v1/setups/{sid}", headers=_auth(uid)).json()["versions"][0]
    client.post(f"/v1/setups/{sid}/versions", json={"rule": "close < open"}, headers=_auth(uid))
    forked = client.post(
        f"/v1/setups/{sid}/fork", json={"name": "Copy", "version_id": v1["id"]}, headers=_auth(uid)
    ).json()
    assert forked["name"] == "Copy" and forked["latest_version"]["rule_text"] == "close > open"
    assert forked["forked_from_version_id"] == v1["id"]
    wrong = client.post(
        f"/v1/setups/{sid}/fork", json={"version_id": 99999}, headers=_auth(uid)
    )
    assert wrong.status_code == 404


def test_seed_presets_is_idempotent(session: Session) -> None:
    first = seed_presets(session)
    assert set(first.values()) == {"created"}
    again = seed_presets(session)
    assert set(again.values()) == {"unchanged"}
    assert len(session.exec(select(Setup).where(col(Setup.is_preset))).all()) == len(PRESETS)
    assert len(session.exec(select(SetupVersion)).all()) == len(PRESETS)


def test_changed_preset_rule_adds_a_version(session: Session, monkeypatch) -> None:
    from dataclasses import replace

    from stockviz.services.setups import presets

    seed_presets(session)
    changed = replace(presets.BREAKOUT, rule="close > highest(high, 252)[1]")
    monkeypatch.setattr(presets, "PRESETS", (changed,))
    assert seed_presets(session) == {changed.key: "new version"}
    setup = session.exec(select(Setup).where(col(Setup.preset_key) == changed.key)).one()
    versions = session.exec(
        select(SetupVersion).where(col(SetupVersion.setup_id) == setup.id)
    ).all()
    assert sorted(v.version for v in versions) == [1, 2]


def test_presets_compile_with_documented_sources() -> None:
    from stockviz.services.dsl import compile_rule

    for preset in PRESETS:
        rule = compile_rule(preset.rule)
        assert rule.type.value == "boolean"
        assert preset.description.startswith("Source:")
    piotroski = next(p for p in PRESETS if p.key == "piotroski-style-quality")
    for criterion in ("F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8", "F9"):
        assert criterion in piotroski.description
    minervini = next(p for p in PRESETS if p.key == "minervini-trend-template")
    assert "rs(252)" in minervini.rule and "rs(252)" in minervini.description


# --- saved screens with a setup version ----------------------------------------


def test_saved_screen_stores_a_setup_version(session: Session, client: TestClient) -> None:
    seed_presets(session)
    a, b = _user(session, "a@x.dev"), _user(session, "b@x.dev")
    mine = client.post(
        "/v1/setups", json={"name": "Mine", "rule": "close > open"}, headers=_auth(a)
    ).json()
    vid = mine["latest_version"]["id"]
    saved = client.post(
        "/v1/screens",
        json={"name": "With rule", "query": "market=US", "setup_version_id": vid},
        headers=_auth(a),
    )
    assert saved.status_code == 201 and saved.json()["setup_version_id"] == vid
    listed = client.get("/v1/screens", headers=_auth(a)).json()
    assert listed[0]["setup_version_id"] == vid

    # A preset's version is fine for anyone; another user's private one is not.
    preset_vid = next(
        s for s in client.get("/v1/setups", headers=_auth(b)).json() if s["is_preset"]
    )["latest_version"]["id"]
    ok = client.post(
        "/v1/screens",
        json={"name": "Preset", "query": "", "setup_version_id": preset_vid},
        headers=_auth(b),
    )
    assert ok.status_code == 201
    refused = client.post(
        "/v1/screens",
        json={"name": "Theirs", "query": "", "setup_version_id": vid},
        headers=_auth(b),
    )
    assert refused.status_code == 404

    # A plain URL-query screen still works, and replacing by name clears the version.
    plain = client.post(
        "/v1/screens", json={"name": "With rule", "query": "market=IN"}, headers=_auth(a)
    ).json()
    assert plain["setup_version_id"] is None and plain["query"] == "market=IN"


def test_presets_list_is_public(session: Session, client: TestClient) -> None:
    seed_presets(session)
    uid = _user(session, "a@x.dev")
    client.post("/v1/setups", json={"name": "Mine", "rule": "close > open"}, headers=_auth(uid))
    body = client.get("/v1/setups/presets").json()
    assert {s["name"] for s in body} == {p.name for p in PRESETS}
    assert all(s["is_preset"] and not s["owned"] for s in body)
    assert all(s["latest_version"]["rule_text"] for s in body)
