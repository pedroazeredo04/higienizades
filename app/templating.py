"""Jinja environment plus the handful of display helpers the templates need."""

from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi.templating import Jinja2Templates

TEMPLATE_DIR = Path(__file__).parent / "templates"

WEEKDAY_NAMES = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]


def due_label(due: date, today: date) -> str:
    """Human phrasing of a due date: the countdown the dashboard leads with."""
    days = (due - today).days
    if days < -1:
        return f"{-days} days late"
    if days == -1:
        return "1 day late"
    if days == 0:
        return "Due today"
    if days == 1:
        return "Due tomorrow"
    return f"Due in {days} days"


def local_datetime(value: datetime | None, tz_name: str) -> str:
    """Render a stored (naive UTC) timestamp in the household's timezone."""
    if value is None:
        return ""
    try:
        tz = ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError):
        tz = ZoneInfo("UTC")
    return value.replace(tzinfo=ZoneInfo("UTC")).astimezone(tz).strftime("%d %b %Y, %H:%M")


def initials(name: str) -> str:
    parts = [p for p in name.split() if p]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


def build_templates() -> Jinja2Templates:
    templates = Jinja2Templates(directory=str(TEMPLATE_DIR))
    templates.env.filters["due_label"] = due_label
    templates.env.filters["local_datetime"] = local_datetime
    templates.env.filters["initials"] = initials
    templates.env.globals["weekday_names"] = WEEKDAY_NAMES
    return templates


templates = build_templates()
