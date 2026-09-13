"""Registration, login, logout.

The first person to register becomes admin; everyone after needs the household
join code, which keeps a guest on the wifi from casually creating an account
without any invite-email machinery.
"""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlmodel import func, select

from app.models import User
from app.security import (
    MIN_PASSWORD_LENGTH,
    DbSession,
    color_for,
    hash_password,
    login_user,
    logout_user,
    normalise_username,
    verify_csrf,
    verify_password,
)
from app.services import household as household_service
from app.views import flash, page

router = APIRouter()


@router.get("/login")
def login_form(request: Request, session: DbSession):
    if request.session.get("uid"):
        return RedirectResponse("/", status_code=303)
    return page(
        request,
        "login.html",
        session,
        has_users=household_service.has_any_user(session),
    )


@router.post("/login", dependencies=[Depends(verify_csrf)])
def login(
    request: Request,
    session: DbSession,
    username: str = Form(...),
    password: str = Form(...),
):
    user = session.exec(select(User).where(User.username == normalise_username(username))).first()
    if user is None or not verify_password(password, user.password_hash):
        return page(
            request,
            "login.html",
            session,
            error="Wrong username or password.",
            username=username,
            has_users=True,
            status_code=401,
        )
    if not user.is_active:
        return page(
            request,
            "login.html",
            session,
            error="That account has been deactivated.",
            has_users=True,
            status_code=403,
        )
    login_user(request, user)
    return RedirectResponse("/", status_code=303)


@router.get("/register")
def register_form(request: Request, session: DbSession):
    return page(
        request,
        "register.html",
        session,
        has_users=household_service.has_any_user(session),
    )


@router.post("/register", dependencies=[Depends(verify_csrf)])
def register(
    request: Request,
    session: DbSession,
    username: str = Form(...),
    display_name: str = Form(...),
    password: str = Form(...),
    password_confirm: str = Form(...),
    join_code: str = Form(""),
):
    is_first_user = not household_service.has_any_user(session)
    clean_username = normalise_username(username)

    def fail(message: str):
        return page(
            request,
            "register.html",
            session,
            error=message,
            username=username,
            display_name=display_name,
            has_users=not is_first_user,
            status_code=400,
        )

    if not clean_username.isalnum():
        return fail("Username must be letters and numbers only, no spaces.")
    if len(password) < MIN_PASSWORD_LENGTH:
        return fail(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
    if password != password_confirm:
        return fail("The two passwords do not match.")
    if not display_name.strip():
        return fail("Please enter a display name.")
    if not is_first_user:
        expected = household_service.get_setting(session, household_service.JOIN_CODE)
        if join_code.strip().upper() != expected:
            return fail("That household code is not right. Ask a flatmate for it.")
    if session.exec(select(User).where(User.username == clean_username)).first():
        return fail("That username is taken.")

    user_count = session.exec(select(func.count(User.id))).one() or 0
    user = User(
        username=clean_username,
        display_name=display_name.strip(),
        password_hash=hash_password(password),
        color=color_for(user_count),
        is_admin=is_first_user,
    )
    session.add(user)
    session.commit()
    session.refresh(user)

    login_user(request, user)
    flash(
        request,
        "Welcome! You are the household admin." if is_first_user else "Welcome aboard!",
        "success",
    )
    return RedirectResponse("/", status_code=303)


@router.post("/logout", dependencies=[Depends(verify_csrf)])
def logout(request: Request):
    logout_user(request)
    return RedirectResponse("/login", status_code=303)
