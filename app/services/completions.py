"""Ticking chores off, and the ways that can be walked back.

Every state change here also generates the chore's successor occurrence, which
is what keeps exactly one open instance per chore.
"""

from datetime import date, datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, desc, select

from app.models import Chore, ChoreInstance, Completion, InstanceStatus, User, utcnow
from app.scheduling import next_due_date
from app.services import chores as chore_service

UNDO_WINDOW = timedelta(hours=24)


class AlreadyResolved(Exception):
    """Someone else got there first -- two phones, one chore."""


class UndoNotAllowed(Exception):
    pass


def _generate_successor(session: Session, chore: Chore, previous_due: date, today: date) -> None:
    """Queue the next occurrence, or retire the chore if it was one-off."""
    if not chore.is_active:
        return
    following = next_due_date(chore, previous_due, completed_on=today, today=today)
    if following is None:
        chore.is_active = False  # a one-off chore is finished once it is done
        session.add(chore)
    else:
        chore_service.create_instance(session, chore, following)


def complete_instance(
    session: Session,
    instance: ChoreInstance,
    actor: User,
    today: date,
    note: str = "",
) -> Completion:
    """Mark an occurrence done and credit the person who actually did it.

    Credit follows the doer, not the assignee -- both are recorded, so history
    can show "Ana did Bruno's trash run".
    """
    if instance.status != InstanceStatus.PENDING.value:
        raise AlreadyResolved("This chore has already been dealt with.")

    chore = session.get(Chore, instance.chore_id)
    completion = Completion(
        chore_instance_id=instance.id,
        chore_id=chore.id,
        user_id=actor.id,
        assigned_user_id=instance.assigned_user_id,
        points_awarded=chore.points,
        note=note.strip(),
    )
    instance.status = InstanceStatus.DONE.value
    instance.resolved_at = utcnow()
    session.add(instance)
    session.add(completion)

    try:
        # Flush before creating the successor: the one-open-instance index only
        # frees up once this instance is no longer pending.
        session.flush()
        _generate_successor(session, chore, instance.due_date, today)
        session.commit()
    except IntegrityError as exc:
        # The unique key on completion.chore_instance_id means a simultaneous
        # tap from a second phone lands here instead of double-scoring.
        session.rollback()
        raise AlreadyResolved("This chore has already been dealt with.") from exc

    session.refresh(completion)
    return completion


def skip_instance(
    session: Session,
    instance: ChoreInstance,
    actor: User,
    today: date,
    reason: str = "",
) -> None:
    """Write off an occurrence without points, and move to the next one."""
    if instance.status != InstanceStatus.PENDING.value:
        raise AlreadyResolved("This chore has already been dealt with.")

    chore = session.get(Chore, instance.chore_id)
    instance.status = InstanceStatus.SKIPPED.value
    instance.resolved_at = utcnow()
    instance.skipped_by_user_id = actor.id
    instance.skip_reason = reason.strip()
    session.add(instance)

    try:
        session.flush()
        _generate_successor(session, chore, instance.due_date, today)
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise AlreadyResolved("This chore has already been dealt with.") from exc


def postpone_instance(session: Session, instance: ChoreInstance, days: int, today: date) -> None:
    """Push a chore back. Counted from today, not from an already-late due date,
    because "push it two days" means two days from now."""
    if instance.status != InstanceStatus.PENDING.value:
        raise AlreadyResolved("This chore has already been dealt with.")
    instance.due_date = max(instance.due_date, today) + timedelta(days=max(days, 1))
    session.add(instance)
    session.commit()


def can_undo(completion: Completion, actor: User, now: datetime) -> bool:
    """Own completions, or anyone's if you are an admin -- within 24 hours."""
    if not (actor.is_admin or completion.user_id == actor.id):
        return False
    return now - completion.completed_at < UNDO_WINDOW


def undo_completion(session: Session, completion: Completion, actor: User, now: datetime) -> None:
    """Take back a completion: remove the points, reopen the occurrence and
    discard the successor it generated."""
    if not can_undo(completion, actor, now):
        raise UndoNotAllowed("That completion is too old to undo, or is not yours.")

    newest = session.exec(
        select(Completion)
        .where(Completion.chore_id == completion.chore_id)
        .order_by(desc(Completion.completed_at), desc(Completion.id))
    ).first()
    if newest is not None and newest.id != completion.id:
        # Undoing an older completion would mean guessing which successor to
        # discard. Refuse rather than corrupt the chain.
        raise UndoNotAllowed("A newer completion of this chore exists; undo that first.")

    chore = session.get(Chore, completion.chore_id)
    instance = (
        session.get(ChoreInstance, completion.chore_instance_id)
        if completion.chore_instance_id
        else None
    )

    successor = chore_service.open_instance(session, completion.chore_id)
    if successor is not None and (instance is None or successor.id != instance.id):
        session.delete(successor)
        session.flush()  # free the one-open-instance index before reopening

    if instance is not None:
        instance.status = InstanceStatus.PENDING.value
        instance.resolved_at = None
        session.add(instance)

    if chore is not None:
        if not chore.is_active and chore_service.is_one_off(chore):
            chore.is_active = True
        # Rewind the rotation pointer so the same person is up again.
        roster_size = len(chore_service.roster(session, chore))
        if roster_size:
            chore.rotation_position = (chore.rotation_position - 1) % roster_size
        session.add(chore)

    session.delete(completion)
    session.commit()
