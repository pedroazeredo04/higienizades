"""Household preferences, flatmate management and your own password."""

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlmodel import select

from app.models import User
from app.security import (
    MIN_PASSWORD_LENGTH,
    AdminUser,
    CurrentUser,
    DbSession,
    hash_password,
    verify_csrf,
    verify_password,
)
from app.services import household as household_service
from app.views import flash, page

router = APIRouter(prefix="/settings")


@router.get("")
def index(request: Request, session: DbSession, user: CurrentUser):
    return page(
        request,
        "settings.html",
        session,
        user,
        flatmates=session.exec(select(User).order_by(User.id)).all(),
    )


@router.post("/household", dependencies=[Depends(verify_csrf)])
def update_household(
    request: Request,
    session: DbSession,
    admin: AdminUser,
    household_name: str = Form(...),
    timezone: str = Form(...),
):
    name = household_name.strip()
    if not name:
        flash(request, "Household name cannot be empty.", "error")
        return RedirectResponse("/settings", status_code=303)
    try:
        ZoneInfo(timezone.strip())
    except (ZoneInfoNotFoundError, ValueError):
        flash(request, f"'{timezone}' is not a known timezone.", "error")
        return RedirectResponse("/settings", status_code=303)

    household_service.set_setting(session, household_service.HOUSEHOLD_NAME, name)
    household_service.set_setting(session, household_service.TIMEZONE, timezone.strip())
    flash(request, "Household settings saved.", "success")
    return RedirectResponse("/settings", status_code=303)


@router.post("/join-code", dependencies=[Depends(verify_csrf)])
def regenerate_join_code(request: Request, session: DbSession, admin: AdminUser):
    code = household_service.regenerate_join_code(session)
    flash(request, f"New household code: {code}", "success")
    return RedirectResponse("/settings", status_code=303)


@router.post("/password", dependencies=[Depends(verify_csrf)])
def change_password(
    request: Request,
    session: DbSession,
    user: CurrentUser,
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
):
    if not verify_password(current_password, user.password_hash):
        flash(request, "Your current password is not right.", "error")
    elif len(new_password) < MIN_PASSWORD_LENGTH:
        flash(request, f"New password must be at least {MIN_PASSWORD_LENGTH} characters.", "error")
    elif new_password != confirm_password:
        flash(request, "The two new passwords do not match.", "error")
    else:
        user.password_hash = hash_password(new_password)
        session.add(user)
        session.commit()
        flash(request, "Password changed.", "success")
    return RedirectResponse("/settings", status_code=303)


@router.post("/users/{user_id}/toggle-active", dependencies=[Depends(verify_csrf)])
def toggle_active(request: Request, session: DbSession, admin: AdminUser, user_id: int):
    """Deactivating drops someone out of rotations but keeps their history and
    their points on the all-time board."""
    target = session.get(User, user_id)
    if target is None:
        return RedirectResponse("/settings", status_code=303)
    if target.id == admin.id:
        flash(request, "You cannot deactivate yourself.", "error")
        return RedirectResponse("/settings", status_code=303)

    target.is_active = not target.is_active
    session.add(target)
    session.commit()
    state = "back on the board" if target.is_active else "deactivated"
    flash(request, f"{target.display_name} is {state}.")
    return RedirectResponse("/settings", status_code=303)


@router.post("/users/{user_id}/toggle-admin", dependencies=[Depends(verify_csrf)])
def toggle_admin(request: Request, session: DbSession, admin: AdminUser, user_id: int):
    target = session.get(User, user_id)
    if target is None:
        return RedirectResponse("/settings", status_code=303)

    admin_count = len(
        [u for u in session.exec(select(User).where(User.is_admin)).all() if u.is_active]
    )
    if target.is_admin and admin_count <= 1:
        flash(request, "The household needs at least one admin.", "error")
        return RedirectResponse("/settings", status_code=303)

    target.is_admin = not target.is_admin
    session.add(target)
    session.commit()
    role = "an admin" if target.is_admin else "no longer an admin"
    flash(request, f"{target.display_name} is {role}.")
    return RedirectResponse("/settings", status_code=303)
