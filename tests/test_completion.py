"""Ticking chores off: points, successors, races and undo."""

from datetime import date, timedelta

from sqlmodel import select

from app.models import Chore, ChoreInstance, Completion, InstanceStatus, User
from app.services import chores as chore_service
from app.services import completions as completion_service
from app.services import household as household_service
from app.services import scoring
from tests.conftest import create_chore, csrf, login, logout, register, resync


def two_flatmates(client, session):
    register(client, "pedro", "Pedro")
    code = household_service.get_setting(session, household_service.JOIN_CODE)
    logout(client)
    register(client, "ana", "Ana", join_code=code)
    logout(client)
    login(client, "pedro")
    resync(session)
    return session.exec(select(User).order_by(User.id)).all()


def open_instance(session, chore_id: int) -> ChoreInstance:
    resync(session)
    instance = chore_service.open_instance(session, chore_id)
    assert instance is not None
    return instance


def complete_via_http(client, instance_id: int) -> None:
    """Post the way the browser does: HTMX request, token in the header."""
    response = client.post(
        f"/instances/{instance_id}/complete",
        data={"mine": "0"},
        headers={"X-CSRF-Token": csrf(client, "/"), "HX-Request": "true"},
    )
    assert response.status_code == 200, response.text


def test_completing_awards_points_and_logs_who_did_it(client, session):
    pedro, _ = two_flatmates(client, session)
    create_chore(client, name="Clean bathroom", points="5")
    chore = session.exec(select(Chore)).one()

    complete_via_http(client, open_instance(session, chore.id).id)

    resync(session)
    completion = session.exec(select(Completion)).one()
    assert completion.points_awarded == 5
    assert completion.user_id == pedro.id


def test_completion_generates_the_next_occurrence_for_the_next_person(client, session):
    pedro, ana = two_flatmates(client, session)
    create_chore(client, name="Take out trash", recurrence="daily")
    chore = session.exec(select(Chore)).one()

    first = open_instance(session, chore.id)
    assert first.assigned_user_id == pedro.id
    complete_via_http(client, first.id)

    second = open_instance(session, chore.id)
    assert second.id != first.id
    assert second.assigned_user_id == ana.id
    assert second.due_date == first.due_date + timedelta(days=1)


def test_only_one_occurrence_is_ever_open(client, session):
    two_flatmates(client, session)
    create_chore(client, recurrence="daily")
    chore = session.exec(select(Chore)).one()

    for _ in range(4):
        complete_via_http(client, open_instance(session, chore.id).id)

    resync(session)
    still_open = session.exec(
        select(ChoreInstance).where(
            ChoreInstance.chore_id == chore.id,
            ChoreInstance.status == InstanceStatus.PENDING.value,
        )
    ).all()
    assert len(still_open) == 1
    assert len(session.exec(select(Completion)).all()) == 4


def test_double_submit_scores_once(client, session):
    """Two phones tapping the same chore at the same time."""
    two_flatmates(client, session)
    create_chore(client, points="3")
    chore = session.exec(select(Chore)).one()
    instance = open_instance(session, chore.id)

    complete_via_http(client, instance.id)
    second = client.post(
        f"/instances/{instance.id}/complete",
        data={"csrf_token": csrf(client, "/"), "mine": "0"},
    )
    assert second.status_code == 200
    assert "already been dealt with" in second.text

    resync(session)
    completions = session.exec(select(Completion)).all()
    assert len(completions) == 1
    assert sum(c.points_awarded for c in completions) == 3


def test_repricing_a_chore_does_not_rewrite_history(client, session):
    two_flatmates(client, session)
    create_chore(client, name="Clean bathroom", points="5", recurrence="daily")
    chore = session.exec(select(Chore)).one()
    complete_via_http(client, open_instance(session, chore.id).id)

    response = client.post(
        f"/chores/{chore.id}",
        data={
            "csrf_token": csrf(client, f"/chores/{chore.id}/edit"),
            "name": "Clean bathroom",
            "description": "",
            "points": "9",
            "recurrence": "daily",
            "assignment_mode": "rotation",
            "apply_to_open": "on",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303

    resync(session)
    assert session.exec(select(Completion)).one().points_awarded == 5
    assert session.exec(select(Chore)).one().points == 9


def test_credit_follows_the_person_who_actually_did_it(client, session):
    pedro, ana = two_flatmates(client, session)
    create_chore(client, name="Trash", points="2", recurrence="daily")
    chore = session.exec(select(Chore)).one()

    instance = open_instance(session, chore.id)
    assert instance.assigned_user_id == pedro.id

    logout(client)
    login(client, "ana")
    complete_via_http(client, instance.id)

    resync(session)
    completion = session.exec(select(Completion)).one()
    assert completion.user_id == ana.id
    assert completion.assigned_user_id == pedro.id


def test_leaderboard_totals_are_all_time_and_include_everyone(client, session):
    pedro, ana = two_flatmates(client, session)
    create_chore(client, name="Trash", points="2", recurrence="daily")
    chore = session.exec(select(Chore)).one()
    for _ in range(3):
        complete_via_http(client, open_instance(session, chore.id).id)

    resync(session)
    rows = scoring.leaderboard(session, date.today())
    by_name = {row.user.display_name: row for row in rows}
    assert by_name["Pedro"].points == 6  # every completion was made by Pedro
    assert by_name["Pedro"].completions == 3
    assert by_name["Ana"].points == 0  # still listed, on zero
    assert rows[0].user.display_name == "Pedro"


def test_one_off_chore_retires_itself(client, session):
    two_flatmates(client, session)
    create_chore(client, name="Assemble shelf", recurrence="once")
    chore = session.exec(select(Chore)).one()

    complete_via_http(client, open_instance(session, chore.id).id)

    resync(session)
    assert session.exec(select(Chore)).one().is_active is False
    assert chore_service.open_instance(session, chore.id) is None


def test_skip_moves_on_without_points(client, session):
    two_flatmates(client, session)
    create_chore(client, name="Trash", points="4", recurrence="daily")
    chore = session.exec(select(Chore)).one()
    first = open_instance(session, chore.id)

    response = client.post(
        f"/instances/{first.id}/skip",
        data={"csrf_token": csrf(client, "/"), "mine": "0", "reason": "away"},
    )
    assert response.status_code == 200

    resync(session)
    assert session.exec(select(Completion)).all() == []
    skipped = session.get(ChoreInstance, first.id)
    assert skipped.status == InstanceStatus.SKIPPED.value
    assert skipped.skip_reason == "away"
    assert chore_service.open_instance(session, chore.id).id != first.id


def test_postpone_counts_from_today_not_from_an_overdue_date(client, session):
    two_flatmates(client, session)
    create_chore(client, recurrence="daily")
    chore = session.exec(select(Chore)).one()
    instance = open_instance(session, chore.id)

    # Pretend the chore has been sitting there for a fortnight.
    instance.due_date = date.today() - timedelta(days=14)
    session.add(instance)
    session.commit()

    response = client.post(
        f"/instances/{instance.id}/postpone",
        data={"csrf_token": csrf(client, "/"), "mine": "0", "days": "2"},
    )
    assert response.status_code == 200

    resync(session)
    assert session.get(ChoreInstance, instance.id).due_date == date.today() + timedelta(days=2)


def test_undo_returns_the_points_and_reopens_the_chore(client, session):
    pedro, _ = two_flatmates(client, session)
    create_chore(client, name="Trash", points="3", recurrence="daily")
    chore = session.exec(select(Chore)).one()
    first = open_instance(session, chore.id)
    complete_via_http(client, first.id)

    resync(session)
    completion = session.exec(select(Completion)).one()
    response = client.post(
        f"/history/{completion.id}/undo",
        data={"csrf_token": csrf(client, "/history")},
        follow_redirects=False,
    )
    assert response.status_code == 303

    resync(session)
    assert session.exec(select(Completion)).all() == []
    assert session.get(ChoreInstance, first.id).status == InstanceStatus.PENDING.value
    assert chore_service.open_instance(session, chore.id).id == first.id

    # The rotation is rewound too, so redoing the chore hands the next one to
    # Ana exactly as it would have before the undo -- not back to Pedro.
    complete_via_http(client, first.id)
    resync(session)
    _, ana = session.exec(select(User).order_by(User.id)).all()
    assert chore_service.open_instance(session, chore.id).assigned_user_id == ana.id


def test_undo_refuses_when_a_newer_completion_exists(client, session):
    two_flatmates(client, session)
    create_chore(client, recurrence="daily")
    chore = session.exec(select(Chore)).one()
    complete_via_http(client, open_instance(session, chore.id).id)
    resync(session)
    older = session.exec(select(Completion)).one()
    complete_via_http(client, open_instance(session, chore.id).id)

    resync(session)
    pedro = session.exec(select(User).order_by(User.id)).first()
    try:
        completion_service.undo_completion(
            session, session.get(Completion, older.id), pedro, older.completed_at
        )
        raise AssertionError("expected UndoNotAllowed")
    except completion_service.UndoNotAllowed as exc:
        assert "newer completion" in str(exc)
