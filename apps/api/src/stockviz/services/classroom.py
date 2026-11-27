"""Cohorts, assignments and the process-only gradebook (A10.2, M12.1, M12.2).

Rules (owner, 27 Nov 2026):

- **Invite codes, opt in.** A student joins with the cohort's code and an
  explicit consent to what the instructor sees; they can leave at any time,
  which removes them from the gradebook (their decks stay theirs).
- **Process only.** The instructor's gradebook reads each assignment deck's
  summary counts (drills, revealed, traded, followed the plan, checks passed of
  applicable) and nothing else: never P&L, R, fills, tickers, dates or books.
  ``GradebookCell`` has no field that could carry them; a test checks.
- **Same drills for everyone.** An assignment fixes the deck recipe, seed
  included, and decks are always anonymised.
- **Rubric:** an assignment meets the rubric when every drill is revealed and
  at least ``min_followed_pct`` of the traded drills followed the plan.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass

from sqlmodel import Session, col, func, select

from stockviz._time import utcnow
from stockviz.models import AssignmentDeck, Cohort, CohortAssignment, CohortMember, User
from stockviz.models.drill import DrillDeck
from stockviz.schemas import DrillDeckIn
from stockviz.services.drills import decks as deck_svc

CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O or 1/I
CODE_LENGTH = 8
MAX_COHORTS_PER_OWNER = 20
MAX_MEMBERS = 200
MAX_ASSIGNMENTS = 50
CONSENT_TEXT = (
    "Your instructor will see, for each assignment, how many drills you revealed and traded, "
    "how many followed your plan and how many plan checks passed. Never your P&L, R, fills, "
    "books or the symbols and dates. You can leave the cohort at any time."
)


class ClassroomError(ValueError):
    """400/422: the request breaks a rule."""


class ClassroomNotFound(LookupError):
    """404: no such cohort or assignment visible to this user."""


class ClassroomConflict(RuntimeError):
    """409: a limit or a state (already a member, already started)."""


def new_code(session: Session) -> str:
    for _ in range(20):
        code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
        if session.exec(select(Cohort).where(Cohort.invite_code == code)).first() is None:
            return code
    raise ClassroomConflict("could not make a unique invite code")


def create_cohort(session: Session, owner_id: int, name: str) -> Cohort:
    owned = session.exec(
        select(func.count()).select_from(Cohort).where(col(Cohort.owner_id) == owner_id)
    ).one()
    if owned >= MAX_COHORTS_PER_OWNER:
        raise ClassroomConflict(f"at most {MAX_COHORTS_PER_OWNER} cohorts per instructor")
    cohort = Cohort(owner_id=owner_id, name=name.strip()[:120], invite_code=new_code(session))
    session.add(cohort)
    session.commit()
    session.refresh(cohort)
    return cohort


def _member(session: Session, cohort_id: int, user_id: int) -> CohortMember | None:
    return session.get(CohortMember, (cohort_id, user_id))


def visible_cohort(session: Session, cohort_id: int, user_id: int) -> tuple[Cohort, str]:
    """The cohort and the caller's role (owner | member); 404 otherwise."""
    cohort = session.get(Cohort, cohort_id)
    if cohort is None:
        raise ClassroomNotFound("cohort not found")
    if cohort.owner_id == user_id:
        return cohort, "owner"
    if _member(session, cohort_id, user_id) is not None:
        return cohort, "member"
    raise ClassroomNotFound("cohort not found")


def owned_cohort(session: Session, cohort_id: int, user_id: int) -> Cohort:
    cohort, role = visible_cohort(session, cohort_id, user_id)
    if role != "owner":
        raise ClassroomNotFound("cohort not found")
    return cohort


def join(session: Session, user_id: int, code: str, consent: bool) -> Cohort:
    if not consent:
        raise ClassroomError("joining needs your consent to what the instructor sees")
    cohort = session.exec(select(Cohort).where(Cohort.invite_code == code.strip().upper())).first()
    if cohort is None or cohort.archived_at is not None:
        raise ClassroomNotFound("no open cohort has that code")
    if cohort.owner_id == user_id:
        raise ClassroomConflict("you are this cohort's instructor")
    if _member(session, cohort.id or 0, user_id) is not None:
        raise ClassroomConflict("you are already a member")
    members = session.exec(
        select(func.count())
        .select_from(CohortMember)
        .where(col(CohortMember.cohort_id) == cohort.id)
    ).one()
    if members >= MAX_MEMBERS:
        raise ClassroomConflict(f"the cohort is full ({MAX_MEMBERS} members)")
    assert cohort.id is not None
    now = utcnow()
    session.add(CohortMember(cohort_id=cohort.id, user_id=user_id, joined_at=now, consented_at=now))
    session.commit()
    return cohort


def leave(session: Session, cohort_id: int, user_id: int) -> None:
    member = _member(session, cohort_id, user_id)
    if member is None:
        raise ClassroomNotFound("cohort not found")
    links = session.exec(
        select(AssignmentDeck)
        .join(CohortAssignment, col(CohortAssignment.id) == col(AssignmentDeck.assignment_id))
        .where(col(CohortAssignment.cohort_id) == cohort_id, col(AssignmentDeck.user_id) == user_id)
    ).all()
    for link in links:
        session.delete(link)  # the decks stay the student's
    session.delete(member)
    session.commit()


def add_assignment(
    session: Session,
    cohort: Cohort,
    title: str,
    recipe: DrillDeckIn,
    min_followed_pct: int,
    due_on=None,
) -> CohortAssignment:
    count = session.exec(
        select(func.count())
        .select_from(CohortAssignment)
        .where(col(CohortAssignment.cohort_id) == cohort.id)
    ).one()
    if count >= MAX_ASSIGNMENTS:
        raise ClassroomConflict(f"at most {MAX_ASSIGNMENTS} assignments per cohort")
    fixed = recipe.model_copy(update={"anonymised": True, "name": title})
    if fixed.seed is None:
        fixed = fixed.model_copy(update={"seed": secrets.randbelow(2**31 - 1)})
    assert cohort.id is not None
    assignment = CohortAssignment(
        cohort_id=cohort.id,
        title=title.strip()[:120],
        recipe=fixed.model_dump(mode="json", by_alias=True),
        min_followed_pct=min_followed_pct,
        due_on=due_on,
    )
    session.add(assignment)
    session.commit()
    session.refresh(assignment)
    return assignment


def start(session: Session, assignment_id: int, user_id: int) -> tuple[AssignmentDeck, bool]:
    """The student's deck for the assignment, made now (``True``) or already made."""
    assignment = session.get(CohortAssignment, assignment_id)
    if assignment is None or _member(session, assignment.cohort_id, user_id) is None:
        raise ClassroomNotFound("assignment not found")
    existing = session.get(AssignmentDeck, (assignment_id, user_id))
    if existing is not None:
        return existing, False
    body = DrillDeckIn.model_validate(assignment.recipe)
    deck = deck_svc.create_deck(session, body, user_id=user_id)
    assert deck.id is not None
    link = AssignmentDeck(assignment_id=assignment_id, user_id=user_id, deck_id=deck.id)
    session.add(link)
    session.commit()
    return link, True


@dataclass(frozen=True)
class GradebookCell:
    """Process counts only. Adding a money, R, fill, ticker or date field breaks the rule."""

    assignment_id: int
    started: bool
    drills: int
    revealed: int
    traded: int
    followed_plan: int
    checks_passed: int
    checks_applicable: int
    followed_pct: float | None
    grade: str  # not_started | in_progress | meets_rubric | below_rubric


@dataclass(frozen=True)
class GradebookRow:
    user_id: int
    name: str
    joined_at: str
    cells: list[GradebookCell]


def grade(cell_counts: dict[str, int], min_followed_pct: int) -> tuple[float | None, str]:
    traded = cell_counts["traded"]
    pct = 100 * cell_counts["followed_plan"] / traded if traded else None
    if cell_counts["revealed"] < cell_counts["drills"]:
        return pct, "in_progress"
    if pct is not None and pct >= min_followed_pct:
        return pct, "meets_rubric"
    return pct, "below_rubric"


def gradebook(
    session: Session, cohort: Cohort
) -> tuple[list[CohortAssignment], list[GradebookRow]]:
    assignments = list(
        session.exec(
            select(CohortAssignment)
            .where(CohortAssignment.cohort_id == cohort.id)
            .order_by(col(CohortAssignment.id))
        ).all()
    )
    members = session.exec(
        select(CohortMember, User)
        .join(User, col(User.id) == col(CohortMember.user_id))
        .where(CohortMember.cohort_id == cohort.id)
        .order_by(col(CohortMember.joined_at))
    ).all()
    rows: list[GradebookRow] = []
    for member, user in members:
        cells: list[GradebookCell] = []
        for a in assignments:
            assert a.id is not None
            link = session.get(AssignmentDeck, (a.id, member.user_id))
            deck = session.get(DrillDeck, link.deck_id) if link else None
            if deck is None:
                cells.append(GradebookCell(a.id, False, 0, 0, 0, 0, 0, 0, None, "not_started"))
                continue
            summary = deck_svc.deck_out(session, deck).summary
            counts = {
                "drills": summary.drills,
                "revealed": summary.revealed,
                "traded": summary.traded,
                "followed_plan": summary.followed_plan,
            }
            pct, label = grade(counts, a.min_followed_pct)
            cells.append(
                GradebookCell(
                    a.id,
                    True,
                    summary.drills,
                    summary.revealed,
                    summary.traded,
                    summary.followed_plan,
                    summary.checks_passed,
                    summary.checks_applicable,
                    pct,
                    label,
                )
            )
        rows.append(
            GradebookRow(
                member.user_id, user.name or "Student", member.joined_at.isoformat(), cells
            )
        )
    return assignments, rows
