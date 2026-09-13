"""Leaderboard and history queries."""

from dataclasses import dataclass
from datetime import date, datetime

from sqlmodel import Session, col, desc, func, select

from app.models import Chore, ChoreInstance, Completion, InstanceStatus, User


@dataclass
class LeaderboardRow:
    user: User
    points: int
    completions: int
    points_per_week: float
    share: float  # 0..1, for the bar width


def leaderboard(
    session: Session,
    today: date,
    since: datetime | None = None,
    since_date: date | None = None,
) -> list[LeaderboardRow]:
    """Points per person, highest first.

    All-time is the default and primary view. Everyone active appears, even on
    zero, so a new roommate is visible rather than missing.

    `points_per_week` is a fairness counterweight: all-time totals structurally
    favour whoever has lived here longest, so this normalises by how long each
    person has actually been around.
    """
    query = select(
        Completion.user_id,
        func.sum(Completion.points_awarded),
        func.count(Completion.id),
    ).group_by(Completion.user_id)
    if since is not None:
        query = query.where(Completion.completed_at >= since)

    totals = {
        user_id: (int(points or 0), int(count or 0))
        for user_id, points, count in session.exec(query).all()
    }

    users = session.exec(select(User).where(User.is_active).order_by(User.id)).all()
    # Keep departed roommates on the all-time board if they scored.
    users = list(users) + [
        u
        for u in session.exec(select(User).where(~col(User.is_active))).all()
        if totals.get(u.id, (0, 0))[0] > 0
    ]

    best = max((totals.get(u.id, (0, 0))[0] for u in users), default=0)
    rows = []
    for user in users:
        points, count = totals.get(user.id, (0, 0))
        joined = user.created_at.date()
        scope_start = max(since_date, joined) if since_date else joined
        # Floor the window at a week so someone who joined yesterday does not
        # show an absurd extrapolated rate.
        days = max((today - scope_start).days, 7)
        rows.append(
            LeaderboardRow(
                user=user,
                points=points,
                completions=count,
                points_per_week=round(points * 7 / days, 1),
                share=(points / best) if best else 0.0,
            )
        )
    rows.sort(key=lambda r: (-r.points, r.user.display_name.lower()))
    return rows


@dataclass
class HistoryEntry:
    kind: str  # "done" | "skipped"
    when: datetime
    chore_name: str
    actor: User | None
    assigned_user: User | None
    points: int
    note: str
    completion_id: int | None


def _completion_entries(
    session: Session, limit: int, user_id: int | None, chore_id: int | None
) -> list[HistoryEntry]:
    query = select(Completion).order_by(desc(Completion.completed_at), desc(Completion.id))
    if user_id:
        query = query.where(Completion.user_id == user_id)
    if chore_id:
        query = query.where(Completion.chore_id == chore_id)
    entries = []
    for c in session.exec(query.limit(limit)).all():
        chore = session.get(Chore, c.chore_id)
        entries.append(
            HistoryEntry(
                kind="done",
                when=c.completed_at,
                chore_name=chore.name if chore else "(deleted chore)",
                actor=session.get(User, c.user_id),
                assigned_user=session.get(User, c.assigned_user_id) if c.assigned_user_id else None,
                points=c.points_awarded,
                note=c.note,
                completion_id=c.id,
            )
        )
    return entries


def _skip_entries(
    session: Session, limit: int, user_id: int | None, chore_id: int | None
) -> list[HistoryEntry]:
    query = (
        select(ChoreInstance)
        .where(
            ChoreInstance.status == InstanceStatus.SKIPPED.value,
            col(ChoreInstance.resolved_at).is_not(None),
        )
        .order_by(desc(ChoreInstance.resolved_at), desc(ChoreInstance.id))
    )
    if user_id:
        query = query.where(ChoreInstance.skipped_by_user_id == user_id)
    if chore_id:
        query = query.where(ChoreInstance.chore_id == chore_id)
    entries = []
    for i in session.exec(query.limit(limit)).all():
        chore = session.get(Chore, i.chore_id)
        entries.append(
            HistoryEntry(
                kind="skipped",
                when=i.resolved_at,
                chore_name=chore.name if chore else "(deleted chore)",
                actor=session.get(User, i.skipped_by_user_id) if i.skipped_by_user_id else None,
                assigned_user=session.get(User, i.assigned_user_id) if i.assigned_user_id else None,
                points=0,
                note=i.skip_reason,
                completion_id=None,
            )
        )
    return entries


def history(
    session: Session,
    page: int = 1,
    per_page: int = 25,
    user_id: int | None = None,
    chore_id: int | None = None,
) -> tuple[list[HistoryEntry], bool]:
    """One page of the activity log, newest first, completions and skips merged.

    Returns `(entries, has_next)`. Both sources are capped at the page window
    before merging, so this stays bounded no matter how long the log grows.
    """
    window = page * per_page + 1
    entries = _completion_entries(session, window, user_id, chore_id) + _skip_entries(
        session, window, user_id, chore_id
    )
    entries.sort(key=lambda e: e.when, reverse=True)
    start = (page - 1) * per_page
    page_entries = entries[start : start + per_page]
    return page_entries, len(entries) > start + per_page
