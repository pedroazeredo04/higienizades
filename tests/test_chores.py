"""Chore CRUD, rosters and the edit semantics for the open occurrence."""

from datetime import date, timedelta

from sqlmodel import select

from app.models import Chore, ChoreInstance, InstanceStatus, User
from app.services import chores as chore_service
from app.services import household as household_service
from tests.conftest import create_chore, csrf, logout, register, resync

SATURDAY = 5


def household_of_two(client, session):
    register(client, "pedro", "Pedro")
    code = household_service.get_setting(session, household_service.JOIN_CODE)
    logout(client)
    register(client, "ana", "Ana", join_code=code)
    resync(session)
    return session.exec(select(User).order_by(User.id)).all()


def edit(client, chore_id: int, **fields):
    payload = {"csrf_token": csrf(client, f"/chores/{chore_id}/edit")}
    payload.update(fields)
    return client.post(f"/chores/{chore_id}", data=payload, follow_redirects=False)


def test_creating_a_chore_opens_its_first_occurrence(client, session):
    household_of_two(client, session)
    create_chore(client, name="Clean bathroom", points="5", recurrence="daily")

    resync(session)
    chore = session.exec(select(Chore)).one()
    assert chore.name == "Clean bathroom"
    assert chore.points == 5
    instance = chore_service.open_instance(session, chore.id)
    assert instance is not None
    assert instance.due_date == date.today()


def test_weekly_chore_starts_on_its_weekday_not_today(client, session):
    household_of_two(client, session)
    create_chore(client, name="Clean bathroom", recurrence="weekly", weekday=str(SATURDAY))

    resync(session)
    chore = session.exec(select(Chore)).one()
    due = chore_service.open_instance(session, chore.id).due_date
    assert due.weekday() == SATURDAY
    assert due >= date.today()


def test_invalid_chore_is_rejected_with_a_message(client, session):
    household_of_two(client, session)
    response = client.post(
        "/chores",
        data={
            "csrf_token": csrf(client, "/chores/new"),
            "name": "",
            "points": "1",
            "recurrence": "weekly",
            "assignment_mode": "rotation",
        },
    )
    assert response.status_code == 400
    assert "Give the chore a name" in response.text
    assert "Pick which day of the week" in response.text
    resync(session)
    assert session.exec(select(Chore)).all() == []


def test_monthly_day_above_28_is_rejected(client, session):
    household_of_two(client, session)
    response = client.post(
        "/chores",
        data={
            "csrf_token": csrf(client, "/chores/new"),
            "name": "Descale kettle",
            "points": "2",
            "recurrence": "monthly",
            "day_of_month": "31",
            "assignment_mode": "rotation",
        },
    )
    assert response.status_code == 400
    assert "February" in response.text


def test_roster_limits_the_rotation_to_the_chosen_flatmates(client, session):
    pedro, ana = household_of_two(client, session)
    create_chore(client, name="Dishes", recurrence="daily", roster_ids=str(ana.id))

    resync(session)
    chore = session.exec(select(Chore)).one()
    assert [u.id for u in chore_service.roster(session, chore)] == [ana.id]
    assert chore_service.open_instance(session, chore.id).assigned_user_id == ana.id


def test_fixed_assignment_always_picks_the_same_person(client, session):
    pedro, ana = household_of_two(client, session)
    create_chore(
        client,
        name="Bins",
        recurrence="daily",
        assignment_mode="fixed",
        fixed_user_id=str(pedro.id),
    )

    resync(session)
    chore = session.exec(select(Chore)).one()
    assert chore_service.open_instance(session, chore.id).assigned_user_id == pedro.id


def test_anyone_chores_are_left_unassigned(client, session):
    household_of_two(client, session)
    create_chore(client, name="Water plants", recurrence="daily", assignment_mode="anyone")

    resync(session)
    chore = session.exec(select(Chore)).one()
    assert chore_service.open_instance(session, chore.id).assigned_user_id is None


def test_renaming_and_repricing_reach_the_open_occurrence_without_migration(client, session):
    household_of_two(client, session)
    create_chore(client, name="Trash", points="1", recurrence="daily")
    resync(session)
    chore = session.exec(select(Chore)).one()
    before = chore_service.open_instance(session, chore.id).id

    edit(
        client,
        chore.id,
        name="Rubbish",
        description="Blue bin",
        points="4",
        recurrence="daily",
        assignment_mode="rotation",
    )

    resync(session)
    chore = session.exec(select(Chore)).one()
    assert (chore.name, chore.points) == ("Rubbish", 4)
    # Same occurrence: nothing about the schedule changed.
    assert chore_service.open_instance(session, chore.id).id == before


def test_schedule_change_moves_the_open_occurrence_when_asked(client, session):
    household_of_two(client, session)
    create_chore(client, name="Bathroom", recurrence="daily")
    resync(session)
    chore = session.exec(select(Chore)).one()
    assert chore_service.open_instance(session, chore.id).due_date == date.today()

    edit(
        client,
        chore.id,
        name="Bathroom",
        points="1",
        recurrence="weekly",
        weekday=str(SATURDAY),
        assignment_mode="rotation",
        apply_to_open="on",
    )

    resync(session)
    due = chore_service.open_instance(session, chore.id).due_date
    assert due.weekday() == SATURDAY


def test_schedule_change_leaves_the_open_occurrence_alone_when_unticked(client, session):
    household_of_two(client, session)
    create_chore(client, name="Bathroom", recurrence="daily")
    resync(session)
    chore = session.exec(select(Chore)).one()
    original_due = chore_service.open_instance(session, chore.id).due_date

    # No apply_to_open field: the checkbox was cleared.
    edit(
        client,
        chore.id,
        name="Bathroom",
        points="1",
        recurrence="weekly",
        weekday=str(SATURDAY),
        assignment_mode="rotation",
    )

    resync(session)
    chore = session.exec(select(Chore)).one()
    assert chore.recurrence == "weekly"
    assert chore_service.open_instance(session, chore.id).due_date == original_due


def test_switching_recurrence_clears_the_fields_that_no_longer_apply(client, session):
    household_of_two(client, session)
    create_chore(client, name="Bathroom", recurrence="weekly", weekday=str(SATURDAY))
    resync(session)
    chore = session.exec(select(Chore)).one()

    edit(
        client,
        chore.id,
        name="Bathroom",
        points="1",
        recurrence="every_n_days",
        interval_n="3",
        weekday=str(SATURDAY),
        assignment_mode="rotation",
    )

    resync(session)
    chore = session.exec(select(Chore)).one()
    assert chore.interval_n == 3
    assert chore.weekday is None


def test_archiving_closes_the_open_occurrence_and_restoring_reopens_one(client, session):
    household_of_two(client, session)
    create_chore(client, name="Trash", recurrence="daily")
    resync(session)
    chore = session.exec(select(Chore)).one()
    instance_id = chore_service.open_instance(session, chore.id).id

    client.post(
        f"/chores/{chore.id}/archive",
        data={"csrf_token": csrf(client, "/chores")},
        follow_redirects=False,
    )
    resync(session)
    assert session.exec(select(Chore)).one().is_active is False
    assert session.get(ChoreInstance, instance_id).status == InstanceStatus.SKIPPED.value
    assert chore_service.open_instance(session, chore.id) is None

    client.post(
        f"/chores/{chore.id}/unarchive",
        data={"csrf_token": csrf(client, "/chores")},
        follow_redirects=False,
    )
    resync(session)
    assert session.exec(select(Chore)).one().is_active is True
    assert chore_service.open_instance(session, chore.id) is not None


def test_archived_chores_stay_off_the_board(client, session):
    household_of_two(client, session)
    create_chore(client, name="Trash", recurrence="daily")
    resync(session)
    chore = session.exec(select(Chore)).one()

    assert 'id="instance-' in client.get("/").text
    client.post(
        f"/chores/{chore.id}/archive",
        data={"csrf_token": csrf(client, "/chores")},
        follow_redirects=False,
    )
    client.get("/")  # consume the flash message so it is not mistaken for a row
    board = client.get("/").text
    assert 'id="instance-' not in board
    assert "Nothing due" in board


def test_explicit_start_date_is_honoured(client, session):
    household_of_two(client, session)
    start = date.today() + timedelta(days=10)
    create_chore(client, name="Deep clean", recurrence="daily", start_date=start.isoformat())

    resync(session)
    chore = session.exec(select(Chore)).one()
    assert chore_service.open_instance(session, chore.id).due_date == start


def test_backfill_gives_an_active_chore_its_missing_occurrence(client, session):
    household_of_two(client, session)
    create_chore(client, name="Trash", recurrence="daily")
    resync(session)
    chore = session.exec(select(Chore)).one()

    session.delete(chore_service.open_instance(session, chore.id))
    session.commit()
    assert chore_service.open_instance(session, chore.id) is None

    assert chore_service.backfill_open_instances(session, date.today()) == 1
    assert chore_service.open_instance(session, chore.id) is not None
