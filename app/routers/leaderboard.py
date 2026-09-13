"""All-time points, with optional period views."""

from fastapi import APIRouter, Request

from app.security import CurrentUser, DbSession
from app.services import household as household_service
from app.services import scoring
from app.views import page

router = APIRouter()

PERIODS = {"all": "All time", "month": "This month", "week": "This week"}


@router.get("/leaderboard")
def leaderboard(request: Request, session: DbSession, user: CurrentUser, period: str = "all"):
    if period not in PERIODS:
        period = "all"
    household = household_service.load(session)

    since_date = None
    if period == "month":
        since_date = household_service.start_of_month(household.today)
    elif period == "week":
        since_date = household_service.start_of_week(household.today)

    since = (
        household_service.utc_start_of_day(household.timezone, since_date) if since_date else None
    )
    return page(
        request,
        "leaderboard.html",
        session,
        user,
        rows=scoring.leaderboard(session, household.today, since, since_date),
        period=period,
        periods=PERIODS,
    )
