"""Recurrence and rotation arithmetic.

Deliberately pure: no database, no implicit `date.today()`. Everything the
functions need is passed in, which is what makes the awkward cases (a weekly
chore finished three weeks late, a rotation whose roster shrank) cheap to
unit-test. `tests/test_scheduling.py` is the specification.
"""

from datetime import date, timedelta

from app.models import Chore, Recurrence

MAX_DAY_OF_MONTH = 28  # so a monthly chore always exists, February included


def _weekday_on_or_after(day: date, weekday: int) -> date:
    return day + timedelta(days=(weekday - day.weekday()) % 7)


def _weekday_after(day: date, weekday: int) -> date:
    return _weekday_on_or_after(day + timedelta(days=1), weekday)


def _month_day_on_or_after(day: date, day_of_month: int) -> date:
    if day.day <= day_of_month:
        return day.replace(day=day_of_month)
    year, month = (day.year + 1, 1) if day.month == 12 else (day.year, day.month + 1)
    return date(year, month, day_of_month)


def _month_day_after(day: date, day_of_month: int) -> date:
    return _month_day_on_or_after(day + timedelta(days=1), day_of_month)


def _require(value: int | None, field: str, chore: Chore) -> int:
    if value is None:
        raise ValueError(f"{chore.recurrence} chore {chore.name!r} is missing {field}")
    return value


def first_due_date(chore: Chore, today: date) -> date:
    """When a freshly created (or reactivated) chore first comes due.

    Calendar-anchored recurrences snap to their next natural slot -- creating a
    "Saturdays" chore on a Tuesday should not make it due that Tuesday.
    """
    match Recurrence(chore.recurrence):
        case Recurrence.WEEKLY:
            return _weekday_on_or_after(today, _require(chore.weekday, "a weekday", chore))
        case Recurrence.MONTHLY:
            return _month_day_on_or_after(
                today, _require(chore.day_of_month, "a day of month", chore)
            )
        case _:
            return today


def next_due_date(
    chore: Chore,
    previous_due: date,
    completed_on: date,
    today: date,
) -> date | None:
    """The due date of the successor occurrence, or None if the chore is one-off.

    Two rules do the real work:

    * Calendar recurrences step from the *previous due date*, not from the
      completion date -- a Saturday chore finished late on Monday is due the
      coming Saturday, not Monday+7.
    * If that step still lands in the past (the chore was ignored for weeks),
      re-anchor to today so we emit one upcoming chore rather than a backlog.
    """
    recurrence = Recurrence(chore.recurrence)

    if recurrence is Recurrence.ONCE:
        return None

    if recurrence in (Recurrence.DAILY, Recurrence.EVERY_N_DAYS):
        if recurrence is Recurrence.DAILY:
            step = 1
        else:
            step = max(_require(chore.interval_n, "an interval", chore), 1)
        candidate = previous_due + timedelta(days=step)
        if candidate < today:
            candidate = max(completed_on, today) + timedelta(days=step)
        return candidate

    if recurrence is Recurrence.WEEKLY:
        weekday = _require(chore.weekday, "a weekday", chore)
        candidate = _weekday_after(previous_due, weekday)
        return candidate if candidate >= today else _weekday_on_or_after(today, weekday)

    day_of_month = _require(chore.day_of_month, "a day of month", chore)
    candidate = _month_day_after(previous_due, day_of_month)
    return candidate if candidate >= today else _month_day_on_or_after(today, day_of_month)


def next_assignee(roster: list[int], position: int) -> tuple[int | None, int]:
    """Pick the next person in the rotation.

    Returns `(user_id, position_to_store)`. The modulo means a roster that
    shrank (someone moved out) still resolves to a real person instead of
    running off the end.
    """
    if not roster:
        return None, position
    index = position % len(roster)
    return roster[index], (index + 1) % len(roster)
