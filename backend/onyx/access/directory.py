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
    parents: dict[str, str] = {}
    for department in client.iterate(
        "/open-apis/contact/v3/departments/0/children",
        params={"department_id_type": "open_department_id", "fetch_child": "true"},
    ):
        department_id = api_identifier(str(department["open_department_id"]))
        parents[department_id] = str(department.get("parent_department_id", "0"))
    employees: dict[str, tuple[str, str, list[str], bool]] = {}
    for department_id in ["0", *parents]:
        for member in client.iterate(
            "/open-apis/contact/v3/users/find_by_department",
            params={
                "department_id": department_id,
                "department_id_type": "open_department_id",
                "user_id_type": "user_id",
            },
        ):
            employee_id = api_identifier(str(member["user_id"]))
            email = (
                str(member.get("enterprise_email") or member.get("email") or "")
                .strip()
                .lower()
            )
            if not email or "@" not in email:
                continue
            status = member.get("status")
            if not isinstance(status, dict):
                raise FeishuAPIError("Feishu directory omitted employee status")
            active = status.get("is_activated") is True and not any(
                status.get(key) is True
                for key in ("is_resigned", "is_frozen", "is_exited")
            )
            department_ids = member.get("department_ids")
            if not isinstance(department_ids, list):
                raise FeishuAPIError("Feishu directory omitted department memberships")
            groups = department_ancestors(
                [str(value) for value in department_ids], parents
            )
            if email in employees and employees[email][1] != employee_id:
                raise FeishuAPIError("Duplicate employee email in Feishu directory")
            employees[email] = (email, employee_id, groups, active)
    return list(employees.values())
