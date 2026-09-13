"""Household-wide preferences and the household's notion of "today".

Timezone matters more than it looks: a chore must flip to overdue at local
midnight, not at UTC midnight (which is 9pm the previous evening in Brazil).
"""

import secrets
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlmodel import Session, select

from app.config import get_config
from app.models import Setting

HOUSEHOLD_NAME = "household_name"
TIMEZONE = "timezone"
JOIN_CODE = "join_code"


def _defaults() -> dict[str, str]:
    return {
        HOUSEHOLD_NAME: "Our Flat",
        TIMEZONE: get_config().default_timezone,
        JOIN_CODE: secrets.token_hex(3).upper(),
    }


def get_setting(session: Session, key: str) -> str:
    """Read a setting, creating it from defaults on first access."""
    row = session.get(Setting, key)
    if row is None:
        row = Setting(key=key, value=_defaults()[key])
        session.add(row)
        session.commit()
        session.refresh(row)
    return row.value


def set_setting(session: Session, key: str, value: str) -> None:
    row = session.get(Setting, key)
    if row is None:
        row = Setting(key=key, value=value)
    else:
        row.value = value
    session.add(row)
    session.commit()


def regenerate_join_code(session: Session) -> str:
    code = secrets.token_hex(3).upper()
    set_setting(session, JOIN_CODE, code)
    return code


@dataclass(frozen=True)
class Household:
    name: str
    timezone: str
    join_code: str
    today: date


def load(session: Session) -> Household:
    tz_name = get_setting(session, TIMEZONE)
    try:
        tz = ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError):
        tz = ZoneInfo("UTC")
    return Household(
        name=get_setting(session, HOUSEHOLD_NAME),
        timezone=tz_name,
        join_code=get_setting(session, JOIN_CODE),
        today=datetime.now(tz).date(),
    )


def has_any_user(session: Session) -> bool:
    """False only before the very first registration, which becomes admin."""
    from app.models import User

    return session.exec(select(User.id).limit(1)).first() is not None


def utc_start_of_day(tz_name: str, day: date) -> datetime:
    """Local midnight of `day`, as the naive UTC the database stores.

    Needed so "this week" on the leaderboard means the household's week, not
    a UTC one that starts at 9pm the evening before.
    """
    try:
        tz = ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError):
        tz = ZoneInfo("UTC")
    local_midnight = datetime.combine(day, time.min, tzinfo=tz)
    return local_midnight.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)


def start_of_week(today: date) -> date:
    """Monday of the current week."""
    return today - timedelta(days=today.weekday())


def start_of_month(today: date) -> date:
    return today.replace(day=1)
