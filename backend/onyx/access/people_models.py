"""Work directory display data. These fields do not grant document access."""

from pydantic import BaseModel, ConfigDict, model_validator


class EmployeeDisplay(BaseModel):
    model_config = ConfigDict(frozen=True)

    employee_id: str
    email: str | None
    display_name: str | None = None
    job_title: str | None = None
    avatar_url: str | None = None
    manager_id: str | None = None
    direct_department_ids: list[str]


class DepartmentDisplay(BaseModel):
    model_config = ConfigDict(frozen=True)

    department_id: str
    name: str | None = None
    parent_id: str | None = None


class DirectoryEmployee(EmployeeDisplay):
    # Preserve the original ACL identity; public contact uses enterprise_email only.
    email: str
    enterprise_email: str | None = None
    active: bool
    acl_department_ids: list[str]


class DirectorySnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    employees: list[DirectoryEmployee]
    departments: list[DepartmentDisplay]

    @model_validator(mode="after")
    def validate_unique_records(self) -> "DirectorySnapshot":
        ids = [employee.employee_id for employee in self.employees]
        emails = [employee.email.lower() for employee in self.employees]
        departments = [department.department_id for department in self.departments]
        if len(ids) != len(set(ids)) or len(emails) != len(set(emails)):
            raise ValueError("Directory employee identities must be unique")
        if len(departments) != len(set(departments)):
            raise ValueError("Directory department identities must be unique")
        return self


class PersonProfile(EmployeeDisplay):
    departments: list[DepartmentDisplay] = []


class EmployeePage(BaseModel):
    items: list[PersonProfile]
    total: int
    offset: int
    limit: int


class TeamSummary(DepartmentDisplay):
    member_count: int


class TeamPage(BaseModel):
    items: list[TeamSummary]
    total: int
    offset: int
    limit: int


class TeamDetail(TeamSummary):
    members: EmployeePage


class PersonRelationships(BaseModel):
    manager: PersonProfile | None = None
    direct_reports: list[PersonProfile]
    total_reports: int
    offset: int
    limit: int
    warnings: list[str] = []
