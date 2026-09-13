"""Smoke tests that every page renders, and that the HTMX board response
carries the out-of-band swaps the navbar depends on."""

from datetime import date

from sqlmodel import select

from app.jobs import backup_database
from app.models import Chore
from app.services import chores as chore_service
from app.services import household as household_service
from tests.conftest import create_chore, csrf, logout, register, resync


def setup_household(client, session):
    register(client, "pedro", "Pedro Azeredo")
    code = household_service.get_setting(session, household_service.JOIN_CODE)
    logout(client)
    register(client, "ana", "Ana Lima", join_code=code)
    logout(client)
    from tests.conftest import login

    login(client, "pedro")
    create_chore(client, name="Clean bathroom", points="5", recurrence="weekly", weekday="5")
    create_chore(client, name="Take out trash", points="1", recurrence="daily")
    resync(session)


def test_every_page_renders(client, session):
    setup_household(client, session)
    for path in (
        "/",
        "/?mine=1",
        "/chores",
        "/chores/new",
        "/leaderboard",
        "/leaderboard?period=week",
        "/leaderboard?period=month",
        "/leaderboard?period=nonsense",
        "/history",
        "/history?page_number=2",
        "/settings",
        "/healthz",
        "/manifest.webmanifest",
    ):
        response = client.get(path)
        assert response.status_code == 200, f"{path} -> {response.status_code}"

    chore = session.exec(select(Chore)).first()
    assert client.get(f"/chores/{chore.id}/edit").status_code == 200


def test_board_shows_the_relative_due_label(client, session):
    setup_household(client, session)
    body = client.get("/").text
    assert "Due today" in body  # the daily chore
    assert "Due in" in body or "Due tomorrow" in body  # the weekly one


def test_board_response_carries_out_of_band_swaps(client, session):
    setup_household(client, session)
    chore = session.exec(select(Chore).where(Chore.name == "Take out trash")).one()
    instance = chore_service.open_instance(session, chore.id)

    response = client.post(
        f"/instances/{instance.id}/complete",
        data={"mine": "0"},
        headers={"X-CSRF-Token": csrf(client, "/"), "HX-Request": "true"},
    )
    assert response.status_code == 200
    body = response.text
    assert 'id="board"' in body
    assert 'id="points-chip" hx-swap-oob="true"' in body
    assert 'id="overdue-chip" hx-swap-oob="true"' in body
    assert "+1 point." in body  # the toast, correctly singular


def test_history_lists_completions_and_skips(client, session):
    setup_household(client, session)
    trash = session.exec(select(Chore).where(Chore.name == "Take out trash")).one()
    bathroom = session.exec(select(Chore).where(Chore.name == "Clean bathroom")).one()
    token = csrf(client, "/")

    client.post(
        f"/instances/{chore_service.open_instance(session, trash.id).id}/complete",
        data={"mine": "0"},
        headers={"X-CSRF-Token": token, "HX-Request": "true"},
    )
    resync(session)
    client.post(
        f"/instances/{chore_service.open_instance(session, bathroom.id).id}/skip",
        data={"mine": "0", "reason": "already spotless"},
        headers={"X-CSRF-Token": token, "HX-Request": "true"},
    )

    body = client.get("/history").text
    assert "Take out trash" in body
    assert "Clean bathroom" in body
    assert "skipped" in body
    assert "already spotless" in body
    assert "Undo" in body


def test_leaderboard_period_filter_excludes_older_points(client, session):
    setup_household(client, session)
    trash = session.exec(select(Chore).where(Chore.name == "Take out trash")).one()
    client.post(
        f"/instances/{chore_service.open_instance(session, trash.id).id}/complete",
        data={"mine": "0"},
        headers={"X-CSRF-Token": csrf(client, "/"), "HX-Request": "true"},
    )
    resync(session)

    from app.services import scoring

    all_time = scoring.leaderboard(session, date.today())
    assert max(row.points for row in all_time) == 1

    future = household_service.utc_start_of_day("UTC", date(2099, 1, 1))
    filtered = scoring.leaderboard(session, date.today(), future, date(2099, 1, 1))
    assert all(row.points == 0 for row in filtered)


def test_settings_shows_the_join_code_to_an_admin(client, session):
    setup_household(client, session)
    code = household_service.get_setting(session, household_service.JOIN_CODE)
    assert code in client.get("/settings").text


def test_backup_writes_a_readable_snapshot(client, session, tmp_path, monkeypatch):
    setup_household(client, session)
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path / "backups"))
    from app.config import get_config

    get_config.cache_clear()

    target = backup_database()
    assert target is not None and target.exists()

    import sqlite3

    with sqlite3.connect(target) as conn:
        names = {row[0] for row in conn.execute("select name from chore")}
    assert names == {"Clean bathroom", "Take out trash"}
    get_config.cache_clear()
