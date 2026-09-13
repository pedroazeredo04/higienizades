"""Database tables.

Three record types carry the domain, and the split between them matters:

* `Chore`         -- the *template*: the rule ("bathroom, weekly, Saturdays, 5pt").
* `ChoreInstance` -- one *occurrence* of that rule; what you see and tap.
* `Completion`    -- the permanent history row written when someone ticks it off.

Completions are separate from instances so that history survives chore edits,
and so the leaderboard can sum points that were frozen at the time they were
earned.
"""

from datetime import UTC, date, datetime
from enum import StrEnum

from sqlalchemy import Index, UniqueConstraint, text
from sqlmodel import Field, Relationship, SQLModel


def utcnow() -> datetime:
    """Naive UTC.

    SQLite has no timezone type, so an aware datetime would come back naive on
    the next read and blow up the first comparison. Storing naive UTC
    everywhere keeps that honest; display converts to the household timezone.
    """
    return datetime.now(UTC).replace(tzinfo=None)


class Recurrence(StrEnum):
    ONCE = "once"
    DAILY = "daily"
    EVERY_N_DAYS = "every_n_days"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class AssignmentMode(StrEnum):
    ROTATION = "rotation"
    FIXED = "fixed"
    ANYONE = "anyone"


class InstanceStatus(StrEnum):
    PENDING = "pending"
    DONE = "done"
    SKIPPED = "skipped"


class User(SQLModel, table=True):
    __tablename__ = "user"

    id: int | None = Field(default=None, primary_key=True)
    username: str = Field(index=True, unique=True)  # stored lowercased
    display_name: str
    password_hash: str
    color: str = "#4f46e5"  # avatar chip tint
    is_admin: bool = False
    is_active: bool = True
    created_at: datetime = Field(default_factory=utcnow)


class Chore(SQLModel, table=True):
    __tablename__ = "chore"

    id: int | None = Field(default=None, primary_key=True)
    name: str
    description: str = ""
    points: int = 1

    recurrence: str = Recurrence.WEEKLY.value
    interval_n: int | None = None  # every_n_days
    weekday: int | None = None  # weekly: 0=Monday .. 6=Sunday
    day_of_month: int | None = None  # monthly: 1..28, capped to exist in February

    assignment_mode: str = AssignmentMode.ROTATION.value
    fixed_user_id: int | None = Field(default=None, foreign_key="user.id")
    rotation_position: int = 0  # index into the roster of whoever is up next

    is_active: bool = True
    created_at: datetime = Field(default_factory=utcnow)

    rotation_members: list["ChoreRotationMember"] = Relationship(
        back_populates="chore",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
    fixed_user: User | None = Relationship(
        sa_relationship_kwargs={"foreign_keys": "Chore.fixed_user_id"}
    )


class ChoreRotationMember(SQLModel, table=True):
    """Per-chore rotation roster, so a chore only two people share does not
    drag the whole flat in. An empty roster means "everyone active"."""

    __tablename__ = "chore_rotation_member"
    __table_args__ = (UniqueConstraint("chore_id", "user_id", name="uq_roster_chore_user"),)

    id: int | None = Field(default=None, primary_key=True)
    chore_id: int = Field(foreign_key="chore.id", index=True)
    user_id: int = Field(foreign_key="user.id")
    position: int = 0

    chore: Chore = Relationship(back_populates="rotation_members")
    user: User = Relationship()


class ChoreInstance(SQLModel, table=True):
    __tablename__ = "chore_instance"
    __table_args__ = (
        # At most one *open* occurrence per chore. The whole scheduling design
        # rests on this, so it is enforced in the database rather than only in
        # application code. Note there is deliberately no unique constraint on
        # (chore_id, due_date): archiving and un-archiving a chore on the same
        # day legitimately produces a second instance for that date.
        Index(
            "uq_instance_one_open",
            "chore_id",
            unique=True,
            sqlite_where=text("status = 'pending'"),
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    chore_id: int = Field(foreign_key="chore.id", index=True)
    assigned_user_id: int | None = Field(default=None, foreign_key="user.id")
    due_date: date = Field(index=True)
    status: str = Field(default=InstanceStatus.PENDING.value, index=True)
    created_at: datetime = Field(default_factory=utcnow)

    # Set when the instance stops being pending. Skips carry who and why so
    # they are visible in history rather than silently disappearing.
    resolved_at: datetime | None = Field(default=None, index=True)
    skipped_by_user_id: int | None = Field(default=None, foreign_key="user.id")
    skip_reason: str = ""

    chore: Chore = Relationship()
    assigned_user: User | None = Relationship(
        sa_relationship_kwargs={"foreign_keys": "ChoreInstance.assigned_user_id"}
    )
    skipped_by: User | None = Relationship(
        sa_relationship_kwargs={"foreign_keys": "ChoreInstance.skipped_by_user_id"}
    )


class Completion(SQLModel, table=True):
    __tablename__ = "completion"

    id: int | None = Field(default=None, primary_key=True)
    # Unique, so a double tap from two phones awards points exactly once.
    chore_instance_id: int | None = Field(
        default=None, foreign_key="chore_instance.id", unique=True
    )
    chore_id: int = Field(foreign_key="chore.id", index=True)
    user_id: int = Field(foreign_key="user.id", index=True)  # who actually did it
    assigned_user_id: int | None = Field(default=None, foreign_key="user.id")
    # Frozen at completion time: re-pricing a chore must not rewrite history.
    points_awarded: int = 0
    completed_at: datetime = Field(default_factory=utcnow, index=True)
    note: str = ""

    chore: Chore = Relationship()
    user: User = Relationship(sa_relationship_kwargs={"foreign_keys": "Completion.user_id"})
    assigned_user: User | None = Relationship(
        sa_relationship_kwargs={"foreign_keys": "Completion.assigned_user_id"}
    )


class Setting(SQLModel, table=True):
    """Household preferences that admins edit in the UI."""

    __tablename__ = "setting"

    key: str = Field(primary_key=True)
    value: str
