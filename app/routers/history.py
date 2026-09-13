"""The activity log: every completion and skip, newest first."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlmodel import select

from app.models import Chore, Completion, User, utcnow
from app.security import CurrentUser, DbSession, verify_csrf
from app.services import completions as completion_service
from app.services import scoring
from app.views import flash, page

router = APIRouter()

PER_PAGE = 25


@router.get("/history")
def history(
    request: Request,
    session: DbSession,
    user: CurrentUser,
    page_number: int = 1,
    user_id: int | None = None,
    chore_id: int | None = None,
):
    page_number = max(page_number, 1)
    entries, has_next = scoring.history(
        session, page_number, PER_PAGE, user_id=user_id, chore_id=chore_id
    )
    now = utcnow()
    return page(
        request,
        "history.html",
        session,
        user,
        entries=entries,
        page_number=page_number,
        has_next=has_next,
        filter_user_id=user_id,
        filter_chore_id=chore_id,
        flatmates=session.exec(select(User).order_by(User.id)).all(),
        chores=session.exec(select(Chore).order_by(Chore.name)).all(),
        undoable={
            e.completion_id
            for e in entries
            if e.completion_id
            and completion_service.can_undo(session.get(Completion, e.completion_id), user, now)
        },
    )


@router.post("/history/{completion_id}/undo", dependencies=[Depends(verify_csrf)])
def undo(request: Request, session: DbSession, user: CurrentUser, completion_id: int):
    completion = session.get(Completion, completion_id)
    if completion is None:
        return RedirectResponse("/history", status_code=303)
    try:
        completion_service.undo_completion(session, completion, user, utcnow())
        flash(request, "Completion undone; the chore is back on the board.")
    except completion_service.UndoNotAllowed as exc:
        flash(request, str(exc), "error")
    return RedirectResponse("/history", status_code=303)
