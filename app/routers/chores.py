"""Chore management: create, edit, archive.

Plain pages with POST-redirect-GET rather than HTMX modals -- this is not the
hot path, and full page loads are the more robust choice on a phone.
"""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlmodel import select

from app.forms import ChoreForm, apply_to_chore, form_from_chore, parse_chore_form
from app.models import Chore, ChoreRotationMember, User
from app.scheduling import first_due_date
from app.security import CurrentUser, DbSession, verify_csrf
from app.services import chores as chore_service
from app.services import household as household_service
from app.views import flash, page

router = APIRouter(prefix="/chores")


def _flatmates(session) -> list[User]:
    return list(session.exec(select(User).where(User.is_active).order_by(User.id)).all())


def _roster_ids(session, chore: Chore) -> list[int]:
    return [
        m.user_id
        for m in session.exec(
            select(ChoreRotationMember)
            .where(ChoreRotationMember.chore_id == chore.id)
            .order_by(ChoreRotationMember.position)
        ).all()
    ]


@router.get("")
def index(request: Request, session: DbSession, user: CurrentUser):
    chores = session.exec(select(Chore).order_by(Chore.is_active.desc(), Chore.name)).all()
    return page(
        request,
        "chores.html",
        session,
        user,
        chores=chores,
        open_instances={c.id: chore_service.open_instance(session, c.id) for c in chores},
    )


@router.get("/new")
def new_form(request: Request, session: DbSession, user: CurrentUser):
    return page(
        request,
        "chore_form.html",
        session,
        user,
        form=ChoreForm(),
        chore=None,
        flatmates=_flatmates(session),
    )


@router.post("", dependencies=[Depends(verify_csrf)])
async def create(request: Request, session: DbSession, user: CurrentUser):
    data = parse_chore_form(await request.form(), session)
    if not data.is_valid:
        return page(
            request,
            "chore_form.html",
            session,
            user,
            form=data,
            chore=None,
            flatmates=_flatmates(session),
            status_code=400,
        )

    household = household_service.load(session)
    chore = Chore()
    apply_to_chore(data, chore)
    session.add(chore)
    session.commit()
    session.refresh(chore)

    if data.roster_ids:
        chore_service.set_roster(session, chore, data.roster_ids)
        session.commit()

    due = data.start_date or first_due_date(chore, household.today)
    chore_service.create_instance(session, chore, max(due, household.today))
    session.commit()

    flash(request, f'"{chore.name}" added.', "success")
    return RedirectResponse("/chores", status_code=303)


@router.get("/{chore_id}/edit")
def edit_form(request: Request, session: DbSession, user: CurrentUser, chore_id: int):
    chore = session.get(Chore, chore_id)
    if chore is None:
        return RedirectResponse("/chores", status_code=303)
    return page(
        request,
        "chore_form.html",
        session,
        user,
        form=form_from_chore(chore, _roster_ids(session, chore)),
        chore=chore,
        flatmates=_flatmates(session),
    )


@router.post("/{chore_id}", dependencies=[Depends(verify_csrf)])
async def update(request: Request, session: DbSession, user: CurrentUser, chore_id: int):
    chore = session.get(Chore, chore_id)
    if chore is None:
        return RedirectResponse("/chores", status_code=303)

    data = parse_chore_form(await request.form(), session)
    if not data.is_valid:
        return page(
            request,
            "chore_form.html",
            session,
            user,
            form=data,
            chore=chore,
            flatmates=_flatmates(session),
            status_code=400,
        )

    household = household_service.load(session)
    apply_to_chore(data, chore)
    session.add(chore)
    chore_service.set_roster(session, chore, data.roster_ids)

    # Name, description and points need no migration: the board and the tick
    # handler read them live from the chore. Only schedule and assignment are
    # baked into the open occurrence, so only those are refreshed -- and only
    # if the editor asked for it.
    if data.apply_to_open:
        chore_service.apply_schedule_change(session, chore, household.today)
    session.commit()

    flash(request, f'"{chore.name}" updated.', "success")
    return RedirectResponse("/chores", status_code=303)


@router.post("/{chore_id}/archive", dependencies=[Depends(verify_csrf)])
def archive(request: Request, session: DbSession, user: CurrentUser, chore_id: int):
    chore = session.get(Chore, chore_id)
    if chore is not None:
        chore_service.archive(session, chore)
        flash(request, f'"{chore.name}" archived. Its history still counts.')
    return RedirectResponse("/chores", status_code=303)


@router.post("/{chore_id}/unarchive", dependencies=[Depends(verify_csrf)])
def unarchive(request: Request, session: DbSession, user: CurrentUser, chore_id: int):
    chore = session.get(Chore, chore_id)
    if chore is not None:
        chore_service.unarchive(session, chore, household_service.load(session).today)
        flash(request, f'"{chore.name}" is back on the board.', "success")
    return RedirectResponse("/chores", status_code=303)
