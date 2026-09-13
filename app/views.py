"""Shared rendering helpers, so routers stay thin and templates get a
consistent context (household, nav counters, CSRF, flash messages)."""

from typing import Any

from fastapi import Request
from fastapi.responses import HTMLResponse
from sqlmodel import Session

from app.models import User
from app.security import csrf_token
from app.services import board as board_service
from app.services import household as household_service
from app.templating import templates

FLASH_KEY = "flash"


def flash(request: Request, message: str, level: str = "info") -> None:
    """Queue a one-shot message for the next rendered page."""
    request.session[FLASH_KEY] = {"message": message, "level": level}


def _base_context(request: Request, session: Session, user: User | None) -> dict[str, Any]:
    context: dict[str, Any] = {
        "request": request,
        "user": user,
        "household": household_service.load(session),
        "csrf_token": csrf_token(request),
        "flash": request.session.pop(FLASH_KEY, None),
    }
    if user is not None:
        context["nav"] = board_service.nav_stats(session, user, context["household"].today)
    return context


def page(
    request: Request,
    template: str,
    session: Session,
    user: User | None = None,
    status_code: int = 200,
    **context: Any,
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        template,
        _base_context(request, session, user) | context,
        status_code=status_code,
    )


def board_fragment(
    request: Request,
    session: Session,
    user: User,
    mine_only: bool,
    toast: str | None = None,
    toast_level: str = "info",
) -> HTMLResponse:
    """The dashboard's HTMX response.

    Returns the re-rendered board plus out-of-band swaps for the navbar points
    chip, the overdue badge and the toast slot. Re-rendering the whole board
    rather than a single row keeps it consistent for free: completing a chore
    removes one row and adds its successor somewhere else in the list.
    """
    household = household_service.load(session)
    return templates.TemplateResponse(
        request,
        "partials/board_response.html",
        {
            "request": request,
            "user": user,
            "household": household,
            "csrf_token": csrf_token(request),
            "nav": board_service.nav_stats(session, user, household.today),
            "board": board_service.load(session, household.today, user, mine_only),
            "toast": toast,
            "toast_level": toast_level,
        },
    )
