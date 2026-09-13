"""The board: what is due, and the buttons that resolve it.

This is the only part of the app that uses HTMX for real. Everything else is
plain POST-redirect-GET, which is simpler and degrades better on a phone.
"""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from app.models import ChoreInstance
from app.security import CurrentUser, DbSession, verify_csrf
from app.services import board as board_service
from app.services import completions as completion_service
from app.services import household as household_service
from app.views import board_fragment, page

router = APIRouter()


@router.get("/")
def dashboard(request: Request, session: DbSession, user: CurrentUser, mine: int = 0):
    household = household_service.load(session)
    return page(
        request,
        "dashboard.html",
        session,
        user,
        board=board_service.load(session, household.today, user, mine_only=bool(mine)),
    )


def _resolve(session, instance_id: int) -> ChoreInstance | None:
    return session.get(ChoreInstance, instance_id)


@router.post("/instances/{instance_id}/complete", dependencies=[Depends(verify_csrf)])
def complete(
    request: Request,
    session: DbSession,
    user: CurrentUser,
    instance_id: int,
    mine: int = Form(0),
    note: str = Form(""),
):
    household = household_service.load(session)
    instance = _resolve(session, instance_id)
    if instance is None:
        return board_fragment(request, session, user, bool(mine), "That chore is gone.", "error")
    try:
        completion = completion_service.complete_instance(
            session, instance, user, household.today, note
        )
    except completion_service.AlreadyResolved as exc:
        return board_fragment(request, session, user, bool(mine), str(exc), "error")
    points = completion.points_awarded
    return board_fragment(
        request,
        session,
        user,
        bool(mine),
        f"Nice one! +{points} point{'' if points == 1 else 's'}.",
        "success",
    )


@router.post("/instances/{instance_id}/skip", dependencies=[Depends(verify_csrf)])
def skip(
    request: Request,
    session: DbSession,
    user: CurrentUser,
    instance_id: int,
    mine: int = Form(0),
    reason: str = Form(""),
):
    household = household_service.load(session)
    instance = _resolve(session, instance_id)
    if instance is None:
        return board_fragment(request, session, user, bool(mine), "That chore is gone.", "error")
    try:
        completion_service.skip_instance(session, instance, user, household.today, reason)
    except completion_service.AlreadyResolved as exc:
        return board_fragment(request, session, user, bool(mine), str(exc), "error")
    return board_fragment(request, session, user, bool(mine), "Skipped. No points awarded.")


@router.post("/instances/{instance_id}/postpone", dependencies=[Depends(verify_csrf)])
def postpone(
    request: Request,
    session: DbSession,
    user: CurrentUser,
    instance_id: int,
    days: int = Form(2),
    mine: int = Form(0),
):
    household = household_service.load(session)
    instance = _resolve(session, instance_id)
    if instance is None:
        return board_fragment(request, session, user, bool(mine), "That chore is gone.", "error")
    try:
        completion_service.postpone_instance(session, instance, days, household.today)
    except completion_service.AlreadyResolved as exc:
        return board_fragment(request, session, user, bool(mine), str(exc), "error")
    return board_fragment(request, session, user, bool(mine), f"Pushed back {days} days.")


@router.get("/manifest.webmanifest")
def manifest(session: DbSession):
    """Served dynamically so the home-screen icon carries the household name."""
    name = household_service.get_setting(session, household_service.HOUSEHOLD_NAME)
    return {
        "name": f"{name} chores",
        "short_name": "Chores",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#f6f7f9",
        "theme_color": "#4f46e5",
        "icons": [
            {"src": "/static/icons/icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "/static/icons/icon-512.png", "sizes": "512x512", "type": "image/png"},
        ],
    }


@router.get("/healthz")
def healthz():
    return {"status": "ok"}


@router.get("/favicon.ico")
def favicon():
    return RedirectResponse("/static/icons/icon-192.png", status_code=307)
