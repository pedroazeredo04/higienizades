"""What the dashboard shows: the open occurrences, bucketed by urgency."""

from dataclasses import dataclass, field
from datetime import date

from sqlmodel import Session, col, func, select

from app.models import Chore, ChoreInstance, Completion, InstanceStatus, User


@dataclass
class Board:
    overdue: list[ChoreInstance] = field(default_factory=list)
    due_today: list[ChoreInstance] = field(default_factory=list)
    upcoming: list[ChoreInstance] = field(default_factory=list)
    mine_only: bool = False

    @property
    def is_empty(self) -> bool:
        return not (self.overdue or self.due_today or self.upcoming)


def load(session: Session, today: date, viewer: User, mine_only: bool = False) -> Board:
    """Open occurrences of active chores, split into overdue / today / later.

    "Mine" includes unassigned ("anyone") chores -- they are nobody's job in
    particular, which makes them everybody's.
    """
    query = (
        select(ChoreInstance)
        .join(Chore, col(Chore.id) == col(ChoreInstance.chore_id))
        .where(ChoreInstance.status == InstanceStatus.PENDING.value, Chore.is_active)
        .order_by(ChoreInstance.due_date, Chore.name)
    )
    if mine_only:
        query = query.where(
            (col(ChoreInstance.assigned_user_id) == viewer.id)
            | col(ChoreInstance.assigned_user_id).is_(None)
        )

    board = Board(mine_only=mine_only)
    for instance in session.exec(query).all():
        if instance.due_date < today:
            board.overdue.append(instance)
        elif instance.due_date == today:
            board.due_today.append(instance)
        else:
            board.upcoming.append(instance)
    return board


@dataclass
class NavStats:
    my_points: int
    overdue_count: int


def nav_stats(session: Session, viewer: User, today: date) -> NavStats:
    points = session.exec(
        select(func.sum(Completion.points_awarded)).where(Completion.user_id == viewer.id)
    ).one()
    overdue = session.exec(
        select(func.count(col(ChoreInstance.id)))
        .join(Chore, col(Chore.id) == col(ChoreInstance.chore_id))
        .where(
            ChoreInstance.status == InstanceStatus.PENDING.value,
            Chore.is_active,
            ChoreInstance.due_date < today,
        )
    ).one()
    return NavStats(my_points=int(points or 0), overdue_count=int(overdue or 0))
