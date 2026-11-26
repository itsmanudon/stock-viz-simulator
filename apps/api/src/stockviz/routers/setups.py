"""`/v1/setups` (A2.2): saved rules and their immutable versions. Authed.

- ``GET /presets``: the presets only. Public (60/min), so the screener's
  preset picker works signed out.
- ``GET ""``: the caller's setups and the presets (``include_archived``).
- ``POST ""``: name, kind and rule; the rule becomes version 1.
- ``GET /{id}``: one setup with every version, newest first.
- ``POST /{id}/versions``: a new version (201), or the existing one when the
  rule is already a version of this setup (200, same canonical hash).
- ``POST /{id}/archive``: hide it from the list; versions stay readable.
- ``POST /{id}/fork``: copy a preset's (or your own setup's) version into a
  new setup you own. A rule that reads drawings (A3.3, ``user_scoped``) is
  its owner's alone: another user's fork is 403 (their setup is 404 anyway),
  and no preset can hold one.

Presets are read-only (403 on versions and archive). Another user's setup is
404. A rule that does not compile is 422 with the error's line and column.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlmodel import Session

from stockviz.auth import UserIdDep
from stockviz.db import get_session
from stockviz.limiter import limiter
from stockviz.models.setup import Setup, SetupVersion
from stockviz.schemas import (
    SetupDetailOut,
    SetupForkIn,
    SetupIn,
    SetupOut,
    SetupVersionIn,
    SetupVersionOut,
)
from stockviz.services.dsl import RuleError, compile_rule
from stockviz.services.setups import store
from stockviz.services.setups.rules import compile_or_422

router = APIRouter(prefix="/v1/setups", tags=["setups"])

SessionDep = Annotated[Session, Depends(get_session)]


@lru_cache(maxsize=4096)
def _user_scoped(rule_text: str) -> bool:
    try:
        return compile_rule(rule_text).user_scoped
    except RuleError:  # a version saved under an older grammar
        return False


def version_out(v: SetupVersion) -> SetupVersionOut:
    assert v.id is not None
    return SetupVersionOut(
        id=v.id,
        setup_id=v.setup_id,
        version=v.version,
        rule_text=v.rule_text,
        canonical_text=v.canonical_text,
        rule_hash=v.rule_hash,
        timeframe=v.timeframe,
        notes=v.notes,
        created_at=v.created_at,
        user_scoped=_user_scoped(v.rule_text),
    )


def _fields(row: Setup, user_id: int | None, latest: SetupVersion, count: int) -> dict:
    assert row.id is not None
    return {
        "id": row.id,
        "name": row.name,
        "kind": row.kind,
        "description": row.description,
        "is_preset": row.is_preset,
        "owned": user_id is not None and row.user_id == user_id,
        "forked_from_version_id": row.forked_from_version_id,
        "created_at": row.created_at,
        "archived_at": row.archived_at,
        "latest_version": version_out(latest),
        "version_count": count,
    }


def _detail(session: Session, row: Setup, user_id: int) -> SetupDetailOut:
    assert row.id is not None
    versions = store.versions_of(session, row.id)
    return SetupDetailOut(
        **_fields(row, user_id, versions[0], len(versions)),
        versions=[version_out(v) for v in versions],
    )


def _not_found(setup_id: int) -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, f"Setup {setup_id} not found")


def _owned(session: Session, setup_id: int, user_id: int) -> Setup:
    try:
        return store.get_owned(session, setup_id, user_id)
    except store.SetupNotFound as exc:
        raise _not_found(setup_id) from exc
    except store.PresetReadOnly as exc:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Presets are read-only: fork it to change it"
        ) from exc


def _listed(session: Session, rows: list[Setup], user_id: int | None) -> list[SetupOut]:
    latest = store.latest_versions(session, [r.id for r in rows if r.id is not None])
    out: list[SetupOut] = []
    for row in rows:
        assert row.id is not None
        if row.id not in latest:  # a setup always has a version; skip a broken row
            continue
        version, count = latest[row.id]
        out.append(SetupOut(**_fields(row, user_id, version, count)))
    return out


@router.get("/presets", response_model=list[SetupOut])
@limiter.limit("60/minute")
def list_presets(request: Request, session: SessionDep) -> list[SetupOut]:
    return _listed(session, store.list_visible(session, None), None)


@router.get("", response_model=list[SetupOut])
def list_setups(
    session: SessionDep,
    user_id: UserIdDep,
    include_archived: Annotated[bool, Query()] = False,
) -> list[SetupOut]:
    rows = store.list_visible(session, user_id, include_archived=include_archived)
    return _listed(session, rows, user_id)


@router.post("", response_model=SetupDetailOut, status_code=status.HTTP_201_CREATED)
def create_setup(body: SetupIn, session: SessionDep, user_id: UserIdDep) -> SetupDetailOut:
    rule = compile_or_422(body.rule)
    try:
        row, _version = store.create_setup(
            session,
            user_id,
            name=body.name.strip(),
            kind=body.kind,
            rule=rule,
            description=body.description,
            notes=body.notes,
            timeframe=body.timeframe,
        )
    except store.SetupLimit as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return _detail(session, row, user_id)


@router.get("/{setup_id}", response_model=SetupDetailOut)
def get_setup(setup_id: int, session: SessionDep, user_id: UserIdDep) -> SetupDetailOut:
    try:
        row = store.get_visible(session, setup_id, user_id)
    except store.SetupNotFound as exc:
        raise _not_found(setup_id) from exc
    return _detail(session, row, user_id)


@router.post(
    "/{setup_id}/versions",
    response_model=SetupVersionOut,
    status_code=status.HTTP_201_CREATED,
    responses={200: {"description": "The rule is already a version of this setup"}},
)
def add_version(
    setup_id: int,
    body: SetupVersionIn,
    response: Response,
    session: SessionDep,
    user_id: UserIdDep,
) -> SetupVersionOut:
    row = _owned(session, setup_id, user_id)
    if row.archived_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Archived setups take no new versions")
    rule = compile_or_422(body.rule)
    try:
        saved = store.add_version(session, row, rule, notes=body.notes, timeframe=body.timeframe)
    except store.SetupLimit as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    if not saved.created:
        response.status_code = status.HTTP_200_OK
    return version_out(saved.version)


@router.post("/{setup_id}/archive", response_model=SetupDetailOut)
def archive_setup(setup_id: int, session: SessionDep, user_id: UserIdDep) -> SetupDetailOut:
    row = _owned(session, setup_id, user_id)
    return _detail(session, store.archive(session, row), user_id)


@router.post("/{setup_id}/fork", response_model=SetupDetailOut, status_code=status.HTTP_201_CREATED)
def fork_setup(
    setup_id: int,
    session: SessionDep,
    user_id: UserIdDep,
    body: SetupForkIn | None = None,
) -> SetupDetailOut:
    body = body or SetupForkIn()
    try:
        source = store.get_visible(session, setup_id, user_id)
    except store.SetupNotFound as exc:
        raise _not_found(setup_id) from exc
    assert source.id is not None
    if body.version_id is not None:
        version = session.get(SetupVersion, body.version_id)
        if version is None or version.setup_id != source.id:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, f"Version {body.version_id} is not in setup {setup_id}"
            )
    else:
        version = store.versions_of(session, source.id)[0]
    try:
        row, _v = store.fork(session, source, user_id, version=version, name=body.name)
    except store.SetupLimit as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except store.UserScopedRule as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
    return _detail(session, row, user_id)
