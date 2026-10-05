"""Run against the repository test database; never seed production data."""

import importlib
import importlib.util
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.access.people_models import (
    DepartmentDisplay,
    DirectoryEmployee,
    DirectorySnapshot,
)
from onyx.db.models import OrgMeshDirectoryUser, User


@pytest.fixture
def db_session(db_session: Session) -> Iterator[Session]:
    """Isolate commits from every test in a rollback-only outer transaction."""
    with db_session.get_bind().connect() as connection:
        transaction = connection.begin()
        with Session(
            bind=connection, join_transaction_mode="create_savepoint"
        ) as isolated:
            yield isolated
        transaction.rollback()


def people_module():
    assert importlib.util.find_spec("onyx.db.people") is not None, (
        "People persistence is missing"
    )
    return importlib.import_module("onyx.db.people")


def directory_snapshot() -> DirectorySnapshot:
    return DirectorySnapshot(
        employees=[
            DirectoryEmployee(
                employee_id="alice",
                email="alice@example.com",
                display_name="Same Name",
                job_title="Developer",
                manager_id="manager",
                direct_department_ids=["team"],
                acl_department_ids=["division", "team"],
                active=True,
            ),
            DirectoryEmployee(
                employee_id="bob",
                email="bob@example.com",
                display_name="Same Name",
                direct_department_ids=["team"],
                acl_department_ids=["division", "team"],
                active=True,
            ),
            DirectoryEmployee(
                employee_id="manager",
                email="manager@example.com",
                display_name=None,
                direct_department_ids=["division"],
                acl_department_ids=["division"],
                active=True,
            ),
        ],
        departments=[
            DepartmentDisplay(department_id="division", name="Engineering"),
            DepartmentDisplay(
                department_id="team", name="Platform", parent_id="division"
            ),
        ],
    )


def seed(session: Session) -> None:
    snapshot = directory_snapshot()
    now = datetime.now(timezone.utc)
    for person in snapshot.employees:
        session.add(
            OrgMeshDirectoryUser(
                email=person.email,
                employee_id=person.employee_id,
                department_ids=person.acl_department_ids,
                active=person.active,
                expires_at=now + timedelta(minutes=15),
                updated_at=now,
            )
        )
    people_module().replace_people_snapshot(session, snapshot)
    session.flush()


def test_duplicate_names_have_stable_ids_and_direct_team_memberships(
    db_session: Session,
) -> None:
    seed(db_session)
    people = people_module()
    page = people.list_people(db_session, "same", "team", 0, 100)
    assert [person.employee_id for person in page.items] == ["alice", "bob"]
    assert page.total == 2
    assert people.list_people(db_session, "", "division", 0, 100).total == 1
    assert people.list_people(db_session, "DEVELOPER", None, 0, 100).total == 1
    assert people.list_people(db_session, "PLATFORM", None, 0, 100).total == 2
    assert people.get_person(db_session, "manager").display_name is None


@pytest.mark.parametrize(
    "state", ["expired", "inactive", "missing", "identity_changed", "disabled_account"]
)
def test_invisible_people_are_excluded_from_every_read(
    db_session: Session, state: str
) -> None:
    seed(db_session)
    record = db_session.get(OrgMeshDirectoryUser, "alice@example.com")
    if state == "expired":
        record.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    elif state == "inactive":
        record.active = False
    elif state == "missing":
        db_session.delete(record)
    elif state == "identity_changed":
        record.employee_id = "replacement"
    else:
        db_session.add(
            User(
                id=uuid4(),
                email="ALICE@example.com",
                hashed_password="test-only",
                is_active=False,
                is_verified=True,
                prior_emails=[],
            )
        )
    db_session.flush()
    people = people_module()
    assert people.get_person(db_session, "alice") is None
    assert "alice" not in {
        person.employee_id
        for person in people.list_people(db_session, "", None, 0, 100).items
    }
    assert "alice" not in {
        person.employee_id
        for person in people.get_relationships(
            db_session, "manager", 0, 100
        ).direct_reports
    }
    team = people.get_team(db_session, "team", 0, 100)
    assert team.members.total == 1


def test_snapshot_persistence_does_not_commit_callers_transaction(
    db_session: Session,
) -> None:
    seed(db_session)
    db_session.rollback()
    assert people_module().list_people(db_session, "", None, 0, 100).total == 0
    assert db_session.scalars(select(OrgMeshDirectoryUser)).all() == []


def test_paging_is_bounded_and_empty_directory_is_typed(db_session: Session) -> None:
    people = people_module()
    assert people.list_people(db_session, "", None, 0, 10).model_dump() == {
        "items": [],
        "total": 0,
        "offset": 0,
        "limit": 10,
    }
    seed(db_session)
    assert len(people.list_people(db_session, "", None, 0, 1).items) == 1
    with pytest.raises(ValueError):
        people.list_people(db_session, "", None, -1, 100)
    with pytest.raises(ValueError):
        people.list_people(db_session, "", None, 0, 101)


def test_manager_cycles_and_missing_managers_terminate(db_session: Session) -> None:
    seed(db_session)
    from onyx.db.models import OrgMeshPerson

    manager = db_session.get(OrgMeshPerson, "manager")
    manager.manager_id = "alice"
    db_session.flush()
    assert (
        "manager_cycle"
        in people_module().get_relationships(db_session, "alice", 0, 100).warnings
    )
    manager.manager_id = "missing"
    db_session.flush()
    result = people_module().get_relationships(db_session, "manager", 0, 100)
    assert result.manager is None
    assert "manager_unavailable" in result.warnings


def test_rich_directory_sync_commits_memberships_and_profiles_together(
    db_session: Session,
) -> None:
    from onyx.db.orgmesh import replace_directory_snapshot

    assert replace_directory_snapshot(db_session, directory_snapshot()) == 3
    assert people_module().list_people(db_session, "", None, 0, 100).total == 3


def test_failed_display_snapshot_rolls_back_membership_updates(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from onyx.db.orgmesh import replace_directory_snapshot

    replace_directory_snapshot(db_session, directory_snapshot())
    before = db_session.get(OrgMeshDirectoryUser, "alice@example.com").updated_at

    def fail(*_args):
        raise ValueError("Invalid display snapshot")

    monkeypatch.setattr(people_module(), "replace_people_snapshot", fail)
    with pytest.raises(ValueError):
        replace_directory_snapshot(db_session, directory_snapshot())
    assert (
        db_session.get(OrgMeshDirectoryUser, "alice@example.com").updated_at == before
    )
    assert people_module().list_people(db_session, "", None, 0, 100).total == 3


def test_successful_sync_never_reactivates_disabled_native_accounts(
    db_session: Session,
) -> None:
    from onyx.db.orgmesh import replace_directory_snapshot

    user = User(
        id=uuid4(),
        email="alice@example.com",
        hashed_password="test-only",
        is_active=False,
        is_verified=True,
        prior_emails=[],
    )
    db_session.add(user)
    db_session.commit()
    replace_directory_snapshot(db_session, directory_snapshot())
    db_session.refresh(user)
    assert user.is_active is False
    assert people_module().get_person(db_session, "alice") is None


def test_invisible_manager_identity_is_not_exposed_in_profile(
    db_session: Session,
) -> None:
    seed(db_session)
    db_session.get(OrgMeshDirectoryUser, "manager@example.com").active = False
    db_session.flush()
    profile = people_module().get_person(db_session, "alice")
    assert profile.manager_id is None
    assert people_module().get_relationships(db_session, "alice", 0, 100).warnings == [
        "manager_unavailable"
    ]


def test_private_identity_never_leaks_through_display_or_search(
    db_session: Session,
) -> None:
    seed(db_session)
    people = people_module()
    private = "alice@example.com"
    profile = people.get_person(db_session, "alice")
    assert profile.email is None
    assert people.list_people(db_session, private, None, 0, 100).total == 0
    page = people.list_people(db_session, "", None, 0, 100)
    assert private not in page.model_dump_json()
    assert private not in people.get_team(db_session, "team", 0, 100).model_dump_json()
    assert (
        private
        not in people.get_relationships(db_session, "manager", 0, 100).model_dump_json()
    )
    assert db_session.get(OrgMeshDirectoryUser, private).email == private
