"""Exercise the real People router with explicit test auth/session boundaries."""

import importlib
import importlib.util
from collections.abc import Iterator
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from onyx.access.people_models import (
    DepartmentDisplay,
    DirectoryEmployee,
    DirectorySnapshot,
)
from onyx.db.models import OrgMeshDirectoryUser


@pytest.fixture
def client(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    assert importlib.util.find_spec("onyx.server.people") is not None, (
        "People router is missing"
    )
    routes = importlib.import_module("onyx.server.people")

    def authenticate(authorization: str | None = Header(default=None)):
        if authorization != "Bearer test-user":
            raise HTTPException(401)
        return SimpleNamespace(id="test-owner", is_active=True)

    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[routes.people_user] = authenticate
    app.dependency_overrides[routes.get_session] = lambda: db_session
    monkeypatch.setattr(
        routes, "load_directory_config", lambda: SimpleNamespace(enabled=True)
    )
    with TestClient(app) as result:
        yield result


def headers() -> dict[str, str]:
    return {"Authorization": "Bearer test-user"}


def seed(db_session: Session) -> None:
    from datetime import datetime, timedelta, timezone

    from onyx.db.people import replace_people_snapshot

    person = DirectoryEmployee(
        employee_id="visible",
        email="visible@example.com",
        display_name="Li",
        direct_department_ids=["team"],
        acl_department_ids=["team"],
        active=True,
        manager_id="missing",
    )
    db_session.add(
        OrgMeshDirectoryUser(
            email=person.email,
            employee_id=person.employee_id,
            active=True,
            department_ids=["team"],
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
            updated_at=datetime.now(timezone.utc),
        )
    )
    replace_people_snapshot(
        db_session,
        DirectorySnapshot(
            employees=[person],
            departments=[DepartmentDisplay(department_id="team", name="Platform")],
        ),
    )
    db_session.flush()


@pytest.mark.parametrize(
    "path",
    [
        "/orgmesh/people",
        "/orgmesh/people/visible",
        "/orgmesh/teams",
        "/orgmesh/teams/team",
        "/orgmesh/people/visible/relationships",
    ],
)
def test_anonymous_cannot_read_any_directory_path(
    client: TestClient, path: str
) -> None:
    assert client.get(path).status_code == 401


@pytest.mark.parametrize(
    "query", ["q=" + "x" * 201, "offset=-1", "limit=0", "limit=101"]
)
def test_invalid_people_query_is_rejected(client: TestClient, query: str) -> None:
    assert client.get("/orgmesh/people?" + query, headers=headers()).status_code == 422


def test_empty_directory_returns_typed_pages_and_hidden_ids_return_404(
    client: TestClient,
) -> None:
    assert client.get("/orgmesh/people", headers=headers()).json() == {
        "items": [],
        "total": 0,
        "offset": 0,
        "limit": 20,
    }
    assert client.get("/orgmesh/teams", headers=headers()).json()["items"] == []
    assert client.get("/orgmesh/people/foreign", headers=headers()).status_code == 404
    assert (
        client.get(
            "/orgmesh/people/foreign/relationships", headers=headers()
        ).status_code
        == 404
    )


def test_profiles_teams_and_missing_relationships(
    client: TestClient, db_session: Session
) -> None:
    seed(db_session)
    assert (
        client.get("/orgmesh/people?q=li&department_id=team", headers=headers()).json()[
            "total"
        ]
        == 1
    )
    assert (
        client.get("/orgmesh/people/visible", headers=headers()).json()["employee_id"]
        == "visible"
    )
    assert (
        client.get("/orgmesh/teams", headers=headers()).json()["items"][0][
            "member_count"
        ]
        == 1
    )
    assert (
        client.get("/orgmesh/teams/team", headers=headers()).json()["members"]["total"]
        == 1
    )
    relationships = client.get(
        "/orgmesh/people/visible/relationships", headers=headers()
    ).json()
    assert relationships["manager"] is None
    assert relationships["warnings"] == ["manager_unavailable"]
    membership = db_session.get(OrgMeshDirectoryUser, "visible@example.com")
    membership.active = False
    db_session.flush()
    assert client.get("/orgmesh/people/visible", headers=headers()).status_code == 404
    assert client.get("/orgmesh/teams/team", headers=headers()).status_code == 404


def test_admin_disabled_directory_returns_no_metadata(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed(db_session)
    routes = importlib.import_module("onyx.server.people")
    monkeypatch.setattr(
        routes, "load_directory_config", lambda: SimpleNamespace(enabled=False)
    )
    assert client.get("/orgmesh/people", headers=headers()).json()["items"] == []
    assert client.get("/orgmesh/people/visible", headers=headers()).status_code == 404
    assert client.get("/orgmesh/teams/team", headers=headers()).status_code == 404


def test_private_fallback_is_not_public_contact_or_search_evidence(
    client: TestClient, db_session: Session
) -> None:
    seed(db_session)
    private = "visible@example.com"
    for path in (
        "/orgmesh/people",
        "/orgmesh/people/visible",
        "/orgmesh/teams/team",
        "/orgmesh/people/visible/relationships",
    ):
        result = client.get(path, headers=headers())
        assert result.status_code == 200
        assert private not in result.text
    assert (
        client.get("/orgmesh/people?q=" + private, headers=headers()).json()["total"]
        == 0
    )
