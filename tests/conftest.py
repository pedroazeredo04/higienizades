"""Test fixtures: a real app against a throwaway SQLite file."""

import re

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel

from app.config import get_config
from app.db import get_engine

# Plain forms carry a hidden field; HTMX requests inherit hx-headers from <body>.
FORM_CSRF = re.compile(r'name="csrf_token" value="([^"]+)"')
HX_CSRF = re.compile(r'hx-headers=\'{"X-CSRF-Token": "([^"]+)"}\'')


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key")
    monkeypatch.setenv("ENABLE_JOBS", "false")
    get_config.cache_clear()
    get_engine.cache_clear()

    SQLModel.metadata.create_all(get_engine())
    from app.main import create_app

    with TestClient(create_app()) as test_client:
        yield test_client

    get_config.cache_clear()
    get_engine.cache_clear()


@pytest.fixture
def session():
    with Session(get_engine()) as db_session:
        yield db_session


def csrf(client: TestClient, path: str = "/login") -> str:
    """Fetch a page and pull its CSRF token out, establishing the session cookie."""
    body = client.get(path).text
    match = FORM_CSRF.search(body) or HX_CSRF.search(body)
    assert match, f"no CSRF token on {path}"
    return match.group(1)


def register(client: TestClient, username: str, name: str, join_code: str = "") -> None:
    response = client.post(
        "/register",
        data={
            "csrf_token": csrf(client, "/register"),
            "username": username,
            "display_name": name,
            "password": "hunter2",
            "password_confirm": "hunter2",
            "join_code": join_code,
        },
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text


def login(client: TestClient, username: str) -> None:
    response = client.post(
        "/login",
        data={"csrf_token": csrf(client), "username": username, "password": "hunter2"},
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text


def logout(client: TestClient) -> None:
    client.post("/logout", data={"csrf_token": csrf(client, "/settings")})


def create_chore(client: TestClient, **overrides) -> None:
    payload = {
        "csrf_token": csrf(client, "/chores/new"),
        "name": "Take out trash",
        "description": "",
        "points": "1",
        "recurrence": "daily",
        "assignment_mode": "rotation",
    }
    payload.update({k: v for k, v in overrides.items()})
    response = client.post("/chores", data=payload, follow_redirects=False)
    assert response.status_code == 303, response.text


def resync(db_session: Session) -> None:
    """End the current read transaction so the next query sees the app's commits.

    The test session is separate from the request sessions, and SQLite gives
    each transaction a stable snapshot.
    """
    db_session.rollback()
    db_session.expire_all()
