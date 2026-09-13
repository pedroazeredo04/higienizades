"""Passwords, cookie sessions, CSRF and the auth dependencies.

Deliberately modest: this runs on a trusted home LAN, so the goal is knowing
who did what, not resisting a determined attacker. See the README for the
one real caveat (plain HTTP means passwords cross the wifi in the clear).
"""

import secrets
from typing import Annotated

from fastapi import Depends, Request
from passlib.context import CryptContext
from sqlmodel import Session

from app.db import get_session
from app.models import User

_pwd = CryptContext(schemes=["argon2"], deprecated="auto")

SESSION_USER_KEY = "uid"
CSRF_KEY = "csrf"
MIN_PASSWORD_LENGTH = 6

# Assigned round-robin so avatars are distinguishable at a glance.
AVATAR_COLORS = [
    "#4f46e5",
    "#0891b2",
    "#059669",
    "#d97706",
    "#dc2626",
    "#7c3aed",
    "#db2777",
    "#65a30d",
]


class NotAuthenticated(Exception):
    """Bounces the browser to the login page."""


class CsrfFailure(Exception):
    """The submitted token did not match the session.

    In practice this almost never means an attack -- it means the browser
    replayed a cached page whose token belongs to an older session, or it is
    not storing the session cookie at all. Both need to be *shown* to the user,
    which is why this is separate from NotAuthenticated: redirecting silently
    back to the form makes a stuck login look like a dead button.
    """


class NotAuthorised(Exception):
    """Signed in, but this needs an admin."""


def hash_password(password: str) -> str:
    return _pwd.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _pwd.verify(password, password_hash)
    except ValueError:
        return False


def normalise_username(username: str) -> str:
    return username.strip().lower()


def color_for(user_count: int) -> str:
    return AVATAR_COLORS[user_count % len(AVATAR_COLORS)]


def login_user(request: Request, user: User) -> None:
    request.session[SESSION_USER_KEY] = user.id
    # New session identity, new CSRF token.
    request.session.pop(CSRF_KEY, None)


def logout_user(request: Request) -> None:
    request.session.clear()


def csrf_token(request: Request) -> str:
    token = request.session.get(CSRF_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        request.session[CSRF_KEY] = token
    return token


async def verify_csrf(request: Request) -> None:
    """Accepts the token from the HTMX header or a plain form field.

    `base.html` puts `hx-headers` on <body>, which HTMX inherits down the DOM,
    so every HTMX request carries it without per-form work; ordinary forms
    post a hidden input instead.
    """
    expected = request.session.get(CSRF_KEY)
    sent = request.headers.get("X-CSRF-Token")
    if not sent:
        form = await request.form()
        sent = str(form.get("csrf_token") or "")
    if not expected or not sent or not secrets.compare_digest(expected, sent):
        raise CsrfFailure


def current_user(request: Request, session: Annotated[Session, Depends(get_session)]) -> User:
    user_id = request.session.get(SESSION_USER_KEY)
    user = session.get(User, user_id) if user_id else None
    if user is None or not user.is_active:
        request.session.clear()
        raise NotAuthenticated
    return user


CurrentUser = Annotated[User, Depends(current_user)]
DbSession = Annotated[Session, Depends(get_session)]


def admin_user(user: CurrentUser) -> User:
    if not user.is_admin:
        raise NotAuthorised
    return user


AdminUser = Annotated[User, Depends(admin_user)]
