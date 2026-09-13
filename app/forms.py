"""Form parsing and validation for chores.

Shared by create and edit so the rules live in exactly one place.
"""

from dataclasses import dataclass, field
from datetime import date

from sqlmodel import Session, select

from app.models import AssignmentMode, Chore, Recurrence, User
from app.scheduling import MAX_DAY_OF_MONTH

MAX_NAME_LENGTH = 80
MAX_POINTS = 100
MAX_INTERVAL_DAYS = 365


def _as_int(raw: object, default: int | None = None) -> int | None:
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return default


@dataclass
class ChoreForm:
    name: str = ""
    description: str = ""
    points: int = 1
    recurrence: str = Recurrence.WEEKLY.value
    interval_n: int | None = None
    weekday: int | None = None
    day_of_month: int | None = None
    assignment_mode: str = AssignmentMode.ROTATION.value
    fixed_user_id: int | None = None
    roster_ids: list[int] = field(default_factory=list)
    start_date: date | None = None
    apply_to_open: bool = True
    errors: list[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return not self.errors


def parse_chore_form(form, session: Session) -> ChoreForm:
    """Read and validate a chore form. Never raises -- collects `errors`."""
    data = ChoreForm(
        name=str(form.get("name") or "").strip(),
        description=str(form.get("description") or "").strip(),
        points=_as_int(form.get("points"), 1),
        recurrence=str(form.get("recurrence") or "").strip(),
        interval_n=_as_int(form.get("interval_n")),
        weekday=_as_int(form.get("weekday")),
        day_of_month=_as_int(form.get("day_of_month")),
        assignment_mode=str(form.get("assignment_mode") or "").strip(),
        fixed_user_id=_as_int(form.get("fixed_user_id")),
        roster_ids=[i for i in (_as_int(v) for v in form.getlist("roster_ids")) if i],
        apply_to_open=form.get("apply_to_open") is not None,
    )

    raw_start = str(form.get("start_date") or "").strip()
    if raw_start:
        try:
            data.start_date = date.fromisoformat(raw_start)
        except ValueError:
            data.errors.append("Start date is not a valid date.")

    if not data.name:
        data.errors.append("Give the chore a name.")
    elif len(data.name) > MAX_NAME_LENGTH:
        data.errors.append(f"Name must be {MAX_NAME_LENGTH} characters or fewer.")

    if data.points is None or not 0 <= data.points <= MAX_POINTS:
        data.errors.append(f"Points must be between 0 and {MAX_POINTS}.")

    try:
        recurrence = Recurrence(data.recurrence)
    except ValueError:
        data.errors.append("Pick how often the chore repeats.")
        recurrence = None

    if recurrence is Recurrence.WEEKLY and (data.weekday is None or not 0 <= data.weekday <= 6):
        data.errors.append("Pick which day of the week.")
    if recurrence is Recurrence.MONTHLY and (
        data.day_of_month is None or not 1 <= data.day_of_month <= MAX_DAY_OF_MONTH
    ):
        data.errors.append(
            f"Day of the month must be between 1 and {MAX_DAY_OF_MONTH} "
            "(so the chore also exists in February)."
        )
    if recurrence is Recurrence.EVERY_N_DAYS and (
        data.interval_n is None or not 1 <= data.interval_n <= MAX_INTERVAL_DAYS
    ):
        data.errors.append(f"Interval must be between 1 and {MAX_INTERVAL_DAYS} days.")

    # Drop fields that do not belong to the chosen recurrence, so an edit from
    # weekly to monthly does not leave a stale weekday behind.
    if recurrence is not Recurrence.WEEKLY:
        data.weekday = None
    if recurrence is not Recurrence.MONTHLY:
        data.day_of_month = None
    if recurrence is not Recurrence.EVERY_N_DAYS:
        data.interval_n = None

    try:
        mode = AssignmentMode(data.assignment_mode)
    except ValueError:
        data.errors.append("Pick who the chore is for.")
        mode = None

    active_ids = {u.id for u in session.exec(select(User).where(User.is_active)).all()}
    if mode is AssignmentMode.FIXED:
        if data.fixed_user_id not in active_ids:
            data.errors.append("Pick which flatmate the chore belongs to.")
    else:
        data.fixed_user_id = None

    if mode is AssignmentMode.ROTATION:
        data.roster_ids = [i for i in data.roster_ids if i in active_ids]
    else:
        data.roster_ids = []

    return data


def apply_to_chore(data: ChoreForm, chore: Chore) -> None:
    """Copy validated form values onto a chore (new or existing)."""
    chore.name = data.name
    chore.description = data.description
    chore.points = data.points
    chore.recurrence = data.recurrence
    chore.interval_n = data.interval_n
    chore.weekday = data.weekday
    chore.day_of_month = data.day_of_month
    chore.assignment_mode = data.assignment_mode
    chore.fixed_user_id = data.fixed_user_id


def form_from_chore(chore: Chore, roster_ids: list[int]) -> ChoreForm:
    return ChoreForm(
        name=chore.name,
        description=chore.description,
        points=chore.points,
        recurrence=chore.recurrence,
        interval_n=chore.interval_n,
        weekday=chore.weekday,
        day_of_month=chore.day_of_month,
        assignment_mode=chore.assignment_mode,
        fixed_user_id=chore.fixed_user_id,
        roster_ids=roster_ids,
    )
