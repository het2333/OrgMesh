from typing import Any
from urllib.parse import urlsplit

from onyx.access.people_models import (
    DepartmentDisplay,
    DirectoryEmployee,
    DirectorySnapshot,
)
from onyx.connectors.feishu.client import FeishuAPIError, FeishuClient, api_identifier


def department_ancestors(departments: list[str], parents: dict[str, str]) -> list[str]:
    result: set[str] = set()
    for department in departments:
        seen: set[str] = set()
        while department and department != "0":
            if department in seen:
                raise FeishuAPIError("Cyclic Feishu department hierarchy")
            seen.add(department)
            result.add(department)
            department = parents.get(department, "")
    return sorted(result)


def fetch_feishu_directory(
    client: FeishuClient,
) -> list[tuple[str, str, list[str], bool]]:
    snapshot = fetch_feishu_directory_snapshot(client)
    return [
        (
            employee.email,
            employee.employee_id,
            employee.acl_department_ids,
            employee.active,
        )
        for employee in snapshot.employees
    ]


def _identifier(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise FeishuAPIError("Feishu directory returned an invalid identity")
    return api_identifier(value)


def _optional_text(value: Any) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str) or len(value) > 2048:
        raise FeishuAPIError("Feishu directory returned invalid work metadata")
    return value.strip() or None


def _avatar(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise FeishuAPIError("Feishu directory returned an invalid avatar")
    url = _optional_text(value.get("avatar_origin") or value.get("avatar_240"))
    if url is None:
        return None
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise FeishuAPIError("Feishu directory returned an invalid avatar URL")
    return url


def fetch_feishu_directory_snapshot(client: FeishuClient) -> DirectorySnapshot:
    """Return a complete authorized crawl, or fail without producing a snapshot."""
    parents: dict[str, str] = {}
    departments: list[DepartmentDisplay] = []
    for department in client.iterate(
        "/open-apis/contact/v3/departments/0/children",
        params={"department_id_type": "open_department_id", "fetch_child": "true"},
    ):
        department_id = _identifier(department.get("open_department_id"))
        parent_id = _identifier(department.get("parent_department_id", "0"))
        if department_id == "0" or department_id in parents:
            raise FeishuAPIError("Duplicate Feishu department identity")
        parents[department_id] = parent_id
        departments.append(
            DepartmentDisplay(
                department_id=department_id,
                name=_optional_text(department.get("name")),
                parent_id=None if parent_id == "0" else parent_id,
            )
        )
    if any(parent != "0" and parent not in parents for parent in parents.values()):
        raise FeishuAPIError("Feishu directory omitted a parent department")
    department_ancestors(list(parents), parents)
    employees: dict[str, DirectoryEmployee] = {}
    employee_emails: dict[str, str] = {}
    for department_id in ["0", *parents]:
        for member in client.iterate(
            "/open-apis/contact/v3/users/find_by_department",
            params={
                "department_id": department_id,
                "department_id_type": "open_department_id",
                "user_id_type": "user_id",
            },
        ):
            employee_id = _identifier(member.get("user_id"))
            enterprise_email = _optional_text(member.get("enterprise_email"))
            if enterprise_email is not None:
                enterprise_email = enterprise_email.lower()
                if "@" not in enterprise_email:
                    raise FeishuAPIError("Feishu returned an invalid enterprise email")
            email = (
                enterprise_email or _optional_text(member.get("email")) or ""
            ).lower()
            status = member.get("status")
            if not isinstance(status, dict):
                raise FeishuAPIError("Feishu directory omitted employee status")
            if not isinstance(status.get("is_activated"), bool) or any(
                key in status and not isinstance(status[key], bool)
                for key in ("is_resigned", "is_frozen", "is_exited")
            ):
                raise FeishuAPIError(
                    "Feishu directory returned invalid employee status"
                )
            active = status.get("is_activated") is True and not any(
                status.get(key) is True
                for key in ("is_resigned", "is_frozen", "is_exited")
            )
            department_ids = member.get("department_ids")
            if not isinstance(department_ids, list):
                raise FeishuAPIError("Feishu directory omitted department memberships")
            direct = sorted({_identifier(value) for value in department_ids} - {"0"})
            if any(value not in parents for value in direct):
                raise FeishuAPIError("Feishu directory omitted an employee department")
            groups = department_ancestors(direct, parents)
            manager_id = _optional_text(member.get("leader_user_id"))
            if manager_id is not None:
                manager_id = _identifier(manager_id)
            employee = DirectoryEmployee(
                employee_id=employee_id,
                email=email,
                enterprise_email=enterprise_email,
                display_name=_optional_text(member.get("name")),
                job_title=_optional_text(member.get("job_title")),
                avatar_url=_avatar(member.get("avatar")),
                manager_id=manager_id,
                direct_department_ids=direct,
                active=active,
                acl_department_ids=groups,
            )
            if not email or "@" not in email:
                continue
            if email in employees and employees[email].employee_id != employee_id:
                raise FeishuAPIError("Duplicate employee email in Feishu directory")
            if employee_id in employee_emails and employee_emails[employee_id] != email:
                raise FeishuAPIError("Duplicate employee ID in Feishu directory")
            if email in employees and employees[email] != employee:
                raise FeishuAPIError("Conflicting repeated Feishu directory employee")
            employee_emails[employee_id] = email
            employees[email] = employee
    return DirectorySnapshot(
        employees=list(employees.values()), departments=departments
    )
