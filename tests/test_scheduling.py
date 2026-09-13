"""Specification for the recurrence and rotation arithmetic.

Dates used below: 2026-09-19 and 2026-09-26 are Saturdays (weekday 5),
2026-09-21 is a Monday, 2026-09-15 is a Tuesday.
"""

from datetime import date

import pytest

from app.models import Chore, Recurrence
from app.scheduling import first_due_date, next_assignee, next_due_date

SATURDAY = 5


def weekly(weekday: int = SATURDAY) -> Chore:
    return Chore(name="Clean bathroom", recurrence=Recurrence.WEEKLY.value, weekday=weekday)


def every_n(n: int) -> Chore:
    return Chore(name="Water plants", recurrence=Recurrence.EVERY_N_DAYS.value, interval_n=n)


def daily() -> Chore:
    return Chore(name="Take out trash", recurrence=Recurrence.DAILY.value)


def monthly(day_of_month: int) -> Chore:
    return Chore(
        name="Descale kettle",
        recurrence=Recurrence.MONTHLY.value,
        day_of_month=day_of_month,
    )


def once() -> Chore:
    return Chore(name="Assemble shelf", recurrence=Recurrence.ONCE.value)


class TestWeekly:
    def test_finished_late_lands_on_the_coming_saturday_not_completion_plus_seven(self):
        # Due Sat 19th, actually done Mon 21st. Naive "+7 days" would say the 28th.
        assert next_due_date(
            weekly(),
            previous_due=date(2026, 9, 19),
            completed_on=date(2026, 9, 21),
            today=date(2026, 9, 21),
        ) == date(2026, 9, 26)

    def test_finished_early_still_steps_from_the_scheduled_date(self):
        assert next_due_date(
            weekly(),
            previous_due=date(2026, 9, 19),
            completed_on=date(2026, 9, 16),
            today=date(2026, 9, 16),
        ) == date(2026, 9, 26)

    def test_ignored_for_six_weeks_re_anchors_instead_of_emitting_a_stale_date(self):
        # Stepping from Aug 1 would give Aug 8, already long past.
        assert next_due_date(
            weekly(),
            previous_due=date(2026, 8, 1),
            completed_on=date(2026, 9, 13),
            today=date(2026, 9, 13),
        ) == date(2026, 9, 19)

    def test_re_anchor_can_land_on_today(self):
        assert next_due_date(
            weekly(),
            previous_due=date(2026, 8, 1),
            completed_on=date(2026, 9, 19),
            today=date(2026, 9, 19),
        ) == date(2026, 9, 19)


class TestIntervals:
    def test_every_three_days_steps_from_the_due_date(self):
        assert next_due_date(
            every_n(3),
            previous_due=date(2026, 9, 10),
            completed_on=date(2026, 9, 10),
            today=date(2026, 9, 10),
        ) == date(2026, 9, 13)

    def test_long_neglect_does_not_produce_an_instantly_overdue_chore(self):
        result = next_due_date(
            every_n(3),
            previous_due=date(2026, 8, 20),
            completed_on=date(2026, 9, 13),
            today=date(2026, 9, 13),
        )
        assert result == date(2026, 9, 16)
        assert result > date(2026, 9, 13)

    def test_daily_steps_by_one(self):
        assert next_due_date(
            daily(),
            previous_due=date(2026, 9, 12),
            completed_on=date(2026, 9, 13),
            today=date(2026, 9, 13),
        ) == date(2026, 9, 13)

    def test_zero_or_negative_interval_cannot_stall_the_chore(self):
        assert next_due_date(
            every_n(0),
            previous_due=date(2026, 9, 10),
            completed_on=date(2026, 9, 10),
            today=date(2026, 9, 10),
        ) == date(2026, 9, 11)


class TestMonthly:
    def test_steps_to_next_month(self):
        assert next_due_date(
            monthly(1),
            previous_due=date(2026, 9, 1),
            completed_on=date(2026, 9, 3),
            today=date(2026, 9, 3),
        ) == date(2026, 10, 1)

    def test_day_28_survives_february(self):
        assert next_due_date(
            monthly(28),
            previous_due=date(2026, 1, 28),
            completed_on=date(2026, 1, 28),
            today=date(2026, 1, 28),
        ) == date(2026, 2, 28)

    def test_december_wraps_the_year(self):
        assert next_due_date(
            monthly(5),
            previous_due=date(2026, 12, 5),
            completed_on=date(2026, 12, 5),
            today=date(2026, 12, 5),
        ) == date(2027, 1, 5)

    def test_neglected_monthly_re_anchors(self):
        assert next_due_date(
            monthly(10),
            previous_due=date(2026, 3, 10),
            completed_on=date(2026, 9, 13),
            today=date(2026, 9, 13),
        ) == date(2026, 10, 10)


class TestOneOff:
    def test_has_no_successor(self):
        assert (
            next_due_date(
                once(),
                previous_due=date(2026, 9, 19),
                completed_on=date(2026, 9, 19),
                today=date(2026, 9, 19),
            )
            is None
        )


class TestFirstDueDate:
    def test_weekly_snaps_forward_to_its_weekday(self):
        # Created on a Tuesday; should not be due that same Tuesday.
        assert first_due_date(weekly(), today=date(2026, 9, 15)) == date(2026, 9, 19)

    def test_weekly_created_on_its_own_weekday_is_due_today(self):
        assert first_due_date(weekly(), today=date(2026, 9, 19)) == date(2026, 9, 19)

    def test_monthly_snaps_to_the_next_matching_day(self):
        assert first_due_date(monthly(1), today=date(2026, 9, 15)) == date(2026, 10, 1)

    def test_interval_chores_start_today(self):
        assert first_due_date(daily(), today=date(2026, 9, 15)) == date(2026, 9, 15)
        assert first_due_date(every_n(4), today=date(2026, 9, 15)) == date(2026, 9, 15)
        assert first_due_date(once(), today=date(2026, 9, 15)) == date(2026, 9, 15)


class TestRotation:
    def test_walks_the_roster_in_order_and_wraps(self):
        assert next_assignee([1, 2, 3], position=0) == (1, 1)
        assert next_assignee([1, 2, 3], position=1) == (2, 2)
        assert next_assignee([1, 2, 3], position=2) == (3, 0)

    def test_position_beyond_the_roster_is_normalised(self):
        assert next_assignee([1, 2, 3], position=5) == (3, 0)

    def test_shrunken_roster_still_resolves_to_a_real_person(self):
        # Someone moved out; the stored position now points past the end.
        assert next_assignee([1, 2], position=2) == (1, 1)

    def test_empty_roster_yields_nobody(self):
        assert next_assignee([], position=3) == (None, 3)


class TestValidation:
    def test_missing_weekday_is_a_clear_error(self):
        broken = Chore(name="Broken", recurrence=Recurrence.WEEKLY.value, weekday=None)
        with pytest.raises(ValueError, match="missing a weekday"):
            next_due_date(broken, date(2026, 9, 1), date(2026, 9, 1), date(2026, 9, 1))
