"""Test complete Feishu snapshots without network access."""

from collections.abc import Iterator
from copy import deepcopy
from typing import Any, cast

import pytest

from onyx.access import directory
from onyx.connectors.feishu.client import FeishuAPIError, FeishuClient


class DirectoryClient:
    def __init__(self, members: list[dict[str, Any]]) -> None:
        self.members = members
        self.departments = [
            {
                "open_department_id": "division",
                "name": "Engineering",
                "parent_department_id": "0",
            },
            {
                "open_department_id": "team",
                "name": "Platform",
                "parent_department_id": "division",
            },
        ]
        self.fail = False

    def iterate(self, path: str, *, params: dict[str, str]) -> Iterator[dict[str, Any]]:
        if "children" in path:
            yield from self.departments
        elif params["department_id"] == "0":
            yield from self.members
            if self.fail:
                raise FeishuAPIError("Interrupted directory crawl")


def member(
    employee_id: str = "employee", email: str = "WORK@example.com"
) -> dict[str, Any]:
    return {
        "user_id": employee_id,
        "enterprise_email": email,
        "department_ids": ["team"],
        "status": {
            "is_activated": True,
            "is_resigned": False,
            "is_frozen": False,
            "is_exited": False,
        },
    }


def snapshot(client: DirectoryClient):
    assert hasattr(directory, "fetch_feishu_directory_snapshot"), (
        "Rich directory snapshot API is missing"
    )
    return directory.fetch_feishu_directory_snapshot(cast(FeishuClient, client))


def test_missing_name_is_not_invented_and_direct_departments_are_separate() -> None:
    result = snapshot(DirectoryClient([member()]))
    employee = result.employees[0]
    assert employee.display_name is None
    assert employee.email == "work@example.com"
    assert employee.direct_department_ids == ["team"]
    assert employee.acl_department_ids == ["division", "team"]
    assert employee.manager_id is None
    assert result.departments[1].name == "Platform"
    assert directory.fetch_feishu_directory(
        cast(FeishuClient, DirectoryClient([member()]))
    ) == [("work@example.com", "employee", ["division", "team"], True)]


def test_authorized_display_fields_are_retained_without_private_fields() -> None:
    value = member()
    value.update(
        name="Li",
        job_title="Engineer",
        leader_user_id="manager",
        avatar={"avatar_origin": "https://example.com/avatar.png"},
        mobile="private",
    )
    employee = snapshot(DirectoryClient([value])).employees[0]
    assert employee.display_name == "Li"
    assert employee.job_title == "Engineer"
    assert employee.manager_id == "manager"
    assert employee.avatar_url == "https://example.com/avatar.png"
    assert "mobile" not in employee.model_dump()


@pytest.mark.parametrize(
    "field,value",
    [
        ("status", None),
        ("status", {"is_activated": "true"}),
        ("department_ids", None),
        ("department_ids", [123]),
        ("name", 123),
    ],
)
def test_malformed_employee_rejects_whole_snapshot(field: str, value: Any) -> None:
    broken = member("other", "other@example.com")
    broken[field] = value
    with pytest.raises((FeishuAPIError, ValueError)):
        snapshot(DirectoryClient([member(), broken]))


def test_conflicting_employee_ids_reject_snapshot() -> None:
    with pytest.raises(FeishuAPIError):
        snapshot(DirectoryClient([member(), member(email="different@example.com")]))


def test_duplicate_department_ids_reject_snapshot() -> None:
    client = DirectoryClient([member()])
    client.departments.append(deepcopy(client.departments[0]))
    with pytest.raises(FeishuAPIError):
        snapshot(client)


def test_incomplete_crawl_never_returns_a_snapshot() -> None:
    client = DirectoryClient([member()])
    client.fail = True
    with pytest.raises(FeishuAPIError):
        snapshot(client)


def test_unknown_department_and_cycle_reject_snapshot() -> None:
    client = DirectoryClient([member()])
    client.departments[0]["parent_department_id"] = "team"
    with pytest.raises(FeishuAPIError):
        snapshot(client)
    client = DirectoryClient([member()])
    client.members[0]["department_ids"] = ["unknown"]
    with pytest.raises(FeishuAPIError):
        snapshot(client)


def test_repeated_identical_member_in_multiple_departments_is_deduplicated() -> None:
    assert len(snapshot(DirectoryClient([member(), member()])).employees) == 1


def test_fallback_email_remains_only_an_acl_identity() -> None:
    value = member()
    del value["enterprise_email"]
    value["email"] = "personal-address@example.invalid"
    result = snapshot(DirectoryClient([value]))
    assert result.employees[0].email == "personal-address@example.invalid"
    assert result.employees[0].model_dump().get("enterprise_email", "missing") is None
    assert (
        directory.fetch_feishu_directory(cast(FeishuClient, DirectoryClient([value])))[
            0
        ][0]
        == "personal-address@example.invalid"
    )


def test_enterprise_email_is_the_only_public_contact_source() -> None:
    value = member()
    value["email"] = "private@example.invalid"
    result = snapshot(DirectoryClient([value]))
    assert (
        result.employees[0].model_dump().get("enterprise_email") == "work@example.com"
    )
