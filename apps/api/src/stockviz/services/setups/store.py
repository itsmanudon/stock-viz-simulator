"""Setups and their versions (A2.2).

Rules of the spine:

- A version is immutable. Nothing here updates a ``setup_versions`` row;
  a new rule is version n+1.
- Saving a rule a setup already has (same canonical hash) returns that
  version and adds nothing, so a version always names one rule.
- Presets (``user_id`` null) are visible to everyone and changed only by the
  seed. A user may fork a preset, or a setup of their own, into a new setup.
- Another user's setup does not exist as far as the caller can tell (404).
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, func, or_, select

from stockviz._time import utcnow
from stockviz.models.setup import Setup, SetupVersion
from stockviz.services.dsl import CompiledRule

MAX_SETUPS_PER_USER = 200
MAX_VERSIONS_PER_SETUP = 500


class SetupNotFound(LookupError):
    pass


class PresetReadOnly(PermissionError):
    pass


class UserScopedRule(PermissionError):
    """A3.3: a rule that reads drawings belongs to one user: no preset holds
    it, and no one else may fork it."""


class SetupLimit(ValueError):
    pass


@dataclass(frozen=True)
class SavedVersion:
    version: SetupVersion
    created: bool


def visible(user_id: int | None):
    """SQL condition: setups ``user_id`` may read (theirs and the presets)."""
    if user_id is None:
        return col(Setup.is_preset)
    return or_(col(Setup.is_preset), col(Setup.user_id) == user_id)


def get_visible(session: Session, setup_id: int, user_id: int | None) -> Setup:
    row = session.get(Setup, setup_id)
    if row is None or not (row.is_preset or (user_id is not None and row.user_id == user_id)):
        raise SetupNotFound(setup_id)
    return row


def get_owned(session: Session, setup_id: int, user_id: int) -> Setup:
    """A setup the caller may change: their own. A preset is read-only."""
    row = get_visible(session, setup_id, user_id)
    if row.is_preset:
        raise PresetReadOnly(setup_id)
    return row


def visible_version(session: Session, version_id: int, user_id: int | None) -> SetupVersion:
    version = session.get(SetupVersion, version_id)
    if version is None:
        raise SetupNotFound(version_id)
    get_visible(session, version.setup_id, user_id)
    return version


def versions_of(session: Session, setup_id: int) -> list[SetupVersion]:
    return list(
        session.exec(
            select(SetupVersion)
            .where(col(SetupVersion.setup_id) == setup_id)
            .order_by(col(SetupVersion.version).desc())
        ).all()
    )


def latest_versions(session: Session, setup_ids: list[int]) -> dict[int, tuple[SetupVersion, int]]:
    """Setup id -> (its newest version, how many it has), in two queries."""
    if not setup_ids:
        return {}
    counts = dict(
        session.exec(
            select(SetupVersion.setup_id, func.max(SetupVersion.version))
            .where(col(SetupVersion.setup_id).in_(setup_ids))
            .group_by(col(SetupVersion.setup_id))
        ).all()
    )
    rows = session.exec(
        select(SetupVersion).where(
            or_(
                *(
                    (col(SetupVersion.setup_id) == sid) & (col(SetupVersion.version) == n)
                    for sid, n in counts.items()
                )
            )
        )
    ).all()
    return {v.setup_id: (v, counts[v.setup_id]) for v in rows}


def list_visible(
    session: Session, user_id: int | None, *, include_archived: bool = False
) -> list[Setup]:
    stmt = select(Setup).where(visible(user_id))
    if not include_archived:
        stmt = stmt.where(col(Setup.archived_at).is_(None))
    # Presets first, then the user's own, newest first.
    stmt = stmt.order_by(col(Setup.is_preset).desc(), col(Setup.created_at).desc(), col(Setup.id))
    return list(session.exec(stmt).all())


def _existing(
    session: Session, setup_id: int, rule_hash: str, timeframe: str = "daily", feed: str = "auto"
) -> SetupVersion | None:
    return session.exec(
        select(SetupVersion).where(
            col(SetupVersion.setup_id) == setup_id,
            col(SetupVersion.rule_hash) == rule_hash,
            col(SetupVersion.timeframe) == timeframe,
            col(SetupVersion.feed) == feed,
        )
    ).first()


def version_rule(version: SetupVersion) -> CompiledRule:
    """A6.4: a version's rule compiled for its own timeframe. Raises RuleError."""
    from stockviz.services.dsl import compile_rule

    return compile_rule(version.rule_text, timeframe=version.timeframe)


def add_version(
    session: Session,
    setup: Setup,
    rule: CompiledRule,
    *,
    notes: str | None = None,
    timeframe: str = "daily",
    feed: str = "auto",
    commit: bool = True,
) -> SavedVersion:
    """Version n+1 of ``setup`` for ``rule`` on ``timeframe`` (A6.4: and
    ``feed``), or the version that already holds that."""
    assert setup.id is not None
    if rule.timeframe != timeframe:
        raise ValueError(f"the rule was checked for {rule.timeframe}, not {timeframe}")
    if timeframe == "daily" and feed != "auto":
        raise ValueError("a daily version reads no intraday feed")
    if rule.user_scoped and (setup.is_preset or setup.user_id is None):
        raise UserScopedRule("A preset cannot read drawings: drawing() and avwap() are per user")
    found = _existing(session, setup.id, rule.hash, timeframe, feed)
    if found is not None:
        return SavedVersion(found, created=False)
    newest = session.exec(
        select(func.max(SetupVersion.version)).where(col(SetupVersion.setup_id) == setup.id)
    ).one()
    if (newest or 0) >= MAX_VERSIONS_PER_SETUP:
        raise SetupLimit(f"At most {MAX_VERSIONS_PER_SETUP} versions per setup")
    version = SetupVersion(
        setup_id=setup.id,
        version=(newest or 0) + 1,
        rule_text=rule.text,
        canonical_text=rule.canonical_text,
        rule_hash=rule.hash,
        timeframe=timeframe,
        feed=feed,
        notes=notes,
    )
    session.add(version)
    if not commit:
        session.flush()
        return SavedVersion(version, created=True)
    try:
        session.commit()
    except IntegrityError:
        # A concurrent save of the same rule (or the same number): the other won.
        session.rollback()
        found = _existing(session, setup.id, rule.hash, timeframe, feed)
        if found is None:
            raise
        return SavedVersion(found, created=False)
    session.refresh(version)
    return SavedVersion(version, created=True)


def _check_cap(session: Session, user_id: int) -> None:
    count = session.exec(
        select(func.count()).select_from(Setup).where(col(Setup.user_id) == user_id)
    ).one()
    if count >= MAX_SETUPS_PER_USER:
        raise SetupLimit(f"At most {MAX_SETUPS_PER_USER} setups")


def create_setup(
    session: Session,
    user_id: int,
    *,
    name: str,
    kind: str,
    rule: CompiledRule,
    description: str | None = None,
    notes: str | None = None,
    timeframe: str = "daily",
    feed: str = "auto",
    forked_from_version_id: int | None = None,
) -> tuple[Setup, SetupVersion]:
    """A new setup owned by ``user_id`` with ``rule`` as version 1, in one commit."""
    _check_cap(session, user_id)
    setup = Setup(
        user_id=user_id,
        name=name,
        kind=kind,
        description=description,
        is_preset=False,
        forked_from_version_id=forked_from_version_id,
    )
    session.add(setup)
    session.flush()
    saved = add_version(
        session, setup, rule, notes=notes, timeframe=timeframe, feed=feed, commit=False
    )
    session.commit()
    session.refresh(setup)
    session.refresh(saved.version)
    return setup, saved.version


def fork(
    session: Session,
    source: Setup,
    user_id: int,
    *,
    version: SetupVersion,
    name: str | None = None,
) -> tuple[Setup, SetupVersion]:
    """Copy ``version`` of ``source`` into a new setup owned by ``user_id``."""
    assert version.id is not None
    rule = version_rule(version)
    if rule.user_scoped and source.user_id != user_id:
        raise UserScopedRule("This setup reads its owner's drawings; only its owner can fork it")
    return create_setup(
        session,
        user_id,
        name=name or f"{source.name} (fork)"[:120],
        kind=source.kind,
        rule=rule,
        description=source.description,
        notes=version.notes,
        timeframe=version.timeframe,
        feed=version.feed,
        forked_from_version_id=version.id,
    )


def archive(session: Session, setup: Setup) -> Setup:
    if setup.archived_at is None:
        setup.archived_at = utcnow()
        session.add(setup)
        session.commit()
        session.refresh(setup)
    return setup


__all__ = [
    "MAX_SETUPS_PER_USER",
    "MAX_VERSIONS_PER_SETUP",
    "PresetReadOnly",
    "SavedVersion",
    "SetupLimit",
    "SetupNotFound",
    "UserScopedRule",
    "add_version",
    "archive",
    "create_setup",
    "fork",
    "get_owned",
    "get_visible",
    "latest_versions",
    "list_visible",
    "version_rule",
    "versions_of",
    "visible",
    "visible_version",
]
