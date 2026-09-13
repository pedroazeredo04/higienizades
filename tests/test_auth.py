"""Registration, login and the guards around them."""

from sqlmodel import select

from app.models import User
from app.services import household as household_service
from tests.conftest import csrf, login, logout, register


def test_first_user_becomes_admin(client, session):
    register(client, "pedro", "Pedro Azeredo")
    user = session.exec(select(User)).one()
    assert user.is_admin
    assert user.username == "pedro"


def test_second_user_needs_the_household_code(client, session):
    register(client, "pedro", "Pedro")
    logout(client)

    response = client.post(
        "/register",
        data={
            "csrf_token": csrf(client, "/register"),
            "username": "ana",
            "display_name": "Ana",
            "password": "hunter2",
            "password_confirm": "hunter2",
            "join_code": "WRONG1",
        },
    )
    assert response.status_code == 400
    assert "household code" in response.text
    assert session.exec(select(User)).all().__len__() == 1


def test_second_user_joins_with_the_right_code(client, session):
    register(client, "pedro", "Pedro")
    code = household_service.get_setting(session, household_service.JOIN_CODE)
    logout(client)

    register(client, "ana", "Ana", join_code=code)
    ana = session.exec(select(User).where(User.username == "ana")).one()
    assert ana.is_admin is False
    assert ana.color != session.exec(select(User).where(User.username == "pedro")).one().color


def test_username_is_normalised_and_unique(client, session):
    register(client, "pedro", "Pedro")
    code = household_service.get_setting(session, household_service.JOIN_CODE)
    logout(client)

    response = client.post(
        "/register",
        data={
            "csrf_token": csrf(client, "/register"),
            "username": "PEDRO",
            "display_name": "Impostor",
            "password": "hunter2",
            "password_confirm": "hunter2",
            "join_code": code,
        },
    )
    assert response.status_code == 400
    assert "taken" in response.text


def test_short_password_is_rejected(client):
    response = client.post(
        "/register",
        data={
            "csrf_token": csrf(client, "/register"),
            "username": "pedro",
            "display_name": "Pedro",
            "password": "abc",
            "password_confirm": "abc",
        },
    )
    assert response.status_code == 400
    assert "at least 6" in response.text


def test_login_logout_round_trip(client):
    register(client, "pedro", "Pedro")
    logout(client)

    assert client.get("/", follow_redirects=False).status_code == 303
    login(client, "pedro")
    assert client.get("/").status_code == 200


def test_wrong_password_is_rejected(client):
    register(client, "pedro", "Pedro")
    logout(client)

    response = client.post(
        "/login",
        data={"csrf_token": csrf(client), "username": "pedro", "password": "nope"},
    )
    assert response.status_code == 401
    assert "Wrong username or password" in response.text


def test_unauthenticated_pages_redirect_to_login(client):
    for path in ("/", "/chores", "/leaderboard", "/history", "/settings"):
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 303, path
        assert response.headers["location"] == "/login"


def test_post_without_csrf_token_is_refused(client):
    register(client, "pedro", "Pedro")
    response = client.post(
        "/chores",
        data={"name": "Sneaky", "points": "1", "recurrence": "daily", "assignment_mode": "anyone"},
        follow_redirects=False,
    )
    # Bounced to login rather than accepted.
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_deactivated_user_cannot_use_their_session(client, session):
    register(client, "pedro", "Pedro")
    pedro = session.exec(select(User)).one()
    pedro.is_active = False
    session.add(pedro)
    session.commit()

    assert client.get("/", follow_redirects=False).status_code == 303


def test_non_admin_cannot_change_household_settings(client, session):
    register(client, "pedro", "Pedro")
    code = household_service.get_setting(session, household_service.JOIN_CODE)
    logout(client)
    register(client, "ana", "Ana", join_code=code)

    response = client.post(
        "/settings/household",
        data={
            "csrf_token": csrf(client, "/settings"),
            "household_name": "Hacked",
            "timezone": "UTC",
        },
    )
    assert response.status_code == 403
