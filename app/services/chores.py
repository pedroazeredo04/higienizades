"""Chore lifecycle: rosters, generating occurrences, editing and archiving."""

from datetime import date

from sqlmodel import Session, select

from app.models import (
    AssignmentMode,
    Chore,
    ChoreInstance,
    ChoreRotationMember,
    InstanceStatus,
    Recurrence,
    User,
    utcnow,
)
from app.scheduling import first_due_date, next_assignee


def roster(session: Session, chore: Chore) -> list[User]:
    """Active users eligible for this chore, in rotation order.

    An empty roster means "everyone", which keeps the common case zero-effort.
    """
    members = session.exec(
        select(ChoreRotationMember)
        .where(ChoreRotationMember.chore_id == chore.id)
        .order_by(ChoreRotationMember.position)
    ).all()
    if members:
        users = [session.get(User, m.user_id) for m in members]
        return [u for u in users if u is not None and u.is_active]
    return list(session.exec(select(User).where(User.is_active).order_by(User.id)).all())


def set_roster(session: Session, chore: Chore, user_ids: list[int]) -> None:
    """Replace the chore's rotation roster. An empty list restores "everyone"."""
    for existing in session.exec(
        select(ChoreRotationMember).where(ChoreRotationMember.chore_id == chore.id)
    ).all():
        session.delete(existing)
    for position, user_id in enumerate(user_ids):
        session.add(ChoreRotationMember(chore_id=chore.id, user_id=user_id, position=position))
    chore.rotation_position = 0
    session.add(chore)


def advance_assignment(session: Session, chore: Chore) -> int | None:
    """Decide who gets the next occurrence, advancing the rotation pointer.

    Mutates `chore.rotation_position` -- callers are expected to commit.
    Returns None for "anyone" chores, which nobody owns until someone acts.
    """
    match AssignmentMode(chore.assignment_mode):
        case AssignmentMode.FIXED:
            return chore.fixed_user_id
        case AssignmentMode.ANYONE:
            return None
        case _:
            ids = [u.id for u in roster(session, chore)]
            user_id, next_position = next_assignee(ids, chore.rotation_position)
            chore.rotation_position = next_position
            session.add(chore)
            return user_id


def open_instance(session: Session, chore_id: int) -> ChoreInstance | None:
    return session.exec(
        select(ChoreInstance).where(
            ChoreInstance.chore_id == chore_id,
            ChoreInstance.status == InstanceStatus.PENDING.value,
        )
    ).first()


def create_instance(session: Session, chore: Chore, due_date: date) -> ChoreInstance:
    instance = ChoreInstance(
        chore_id=chore.id,
        assigned_user_id=advance_assignment(session, chore),
        due_date=due_date,
    )
    session.add(instance)
    return instance


def ensure_open_instance(session: Session, chore: Chore, today: date) -> ChoreInstance | None:
    """Give an active chore an open occurrence if it somehow lacks one.

    Covers a brand-new chore, an un-archived one, and the rare case of a crash
    between marking one done and creating its successor.
    """
    if not chore.is_active:
        return None
    existing = open_instance(session, chore.id)
    if existing is not None:
        return existing
    return create_instance(session, chore, first_due_date(chore, today))


def backfill_open_instances(session: Session, today: date) -> int:
    """Safety net run hourly. Returns how many occurrences it had to create."""
    created = 0
    for chore in session.exec(select(Chore).where(Chore.is_active)).all():
        if open_instance(session, chore.id) is None:
            create_instance(session, chore, first_due_date(chore, today))
            created += 1
    if created:
        session.commit()
    return created


def apply_schedule_change(session: Session, chore: Chore, today: date) -> None:
    """Bring the currently open occurrence in line with an edited chore.

    Name, description and points need no migration -- they are read live from
    the chore. Only the schedule and the assignment are baked into an instance,
    so only those are refreshed here.
    """
    instance = open_instance(session, chore.id)
    if instance is None:
        return
    instance.due_date = first_due_date(chore, today)
    instance.assigned_user_id = advance_assignment(session, chore)
    session.add(instance)


def archive(session: Session, chore: Chore) -> None:
    """Retire a chore. Completions stay and keep counting on the leaderboard."""
    chore.is_active = False
    instance = open_instance(session, chore.id)
    if instance is not None:
        instance.status = InstanceStatus.SKIPPED.value
        instance.resolved_at = utcnow()
        instance.skip_reason = "Chore archived"
        session.add(instance)
    session.add(chore)
    session.commit()


def unarchive(session: Session, chore: Chore, today: date) -> None:
    chore.is_active = True
    session.add(chore)
    ensure_open_instance(session, chore, today)
    session.commit()


def is_one_off(chore: Chore) -> bool:
    return Recurrence(chore.recurrence) is Recurrence.ONCE
