"""Read the work directory with the existing membership lifetime boundary."""

from datetime import datetime, timezone

from sqlalchemy import Select, delete, exists, func, or_, select
from sqlalchemy.orm import Session

from onyx.access.people_models import (
    DepartmentDisplay,
    DirectorySnapshot,
    EmployeePage,
    PersonProfile,
    PersonRelationships,
    TeamDetail,
    TeamPage,
    TeamSummary,
)
from onyx.db.models import (
    OrgMeshDepartment,
    OrgMeshDirectoryUser,
    OrgMeshPerson,
    OrgMeshPersonDepartment,
    User,
)


def replace_people_snapshot(db_session: Session, snapshot: DirectorySnapshot) -> None:
    """Replace metadata in the caller's directory transaction; never commit here."""
    snapshot = DirectorySnapshot.model_validate(snapshot.model_dump())
    departments = {department.department_id for department in snapshot.departments}
    if any(
        not set(person.direct_department_ids).issubset(departments)
        for person in snapshot.employees
    ):
        raise ValueError("Display snapshot contains an unknown department")
    db_session.execute(delete(OrgMeshPersonDepartment))
    db_session.execute(delete(OrgMeshPerson))
    db_session.execute(delete(OrgMeshDepartment))
    db_session.add_all(
        [
            OrgMeshDepartment(**department.model_dump())
            for department in snapshot.departments
        ]
    )
    db_session.add_all(
        [
            OrgMeshPerson(
                employee_id=person.employee_id,
                email=person.email.lower(),
                work_email=person.enterprise_email,
                display_name=person.display_name,
                job_title=person.job_title,
                avatar_url=person.avatar_url,
                manager_id=person.manager_id,
            )
            for person in snapshot.employees
        ]
    )
    db_session.flush()
    db_session.add_all(
        [
            OrgMeshPersonDepartment(
                employee_id=person.employee_id, department_id=department
            )
            for person in snapshot.employees
            for department in person.direct_department_ids
        ]
    )
    db_session.flush()


def _visible_people() -> Select[tuple[OrgMeshPerson]]:
    disabled = exists(
        select(User.id).where(
            func.lower(User.email) == OrgMeshPerson.email, User.is_active.is_(False)
        )
    )
    return (
        select(OrgMeshPerson)
        .join(
            OrgMeshDirectoryUser,
            (OrgMeshDirectoryUser.email == OrgMeshPerson.email)
            & (OrgMeshDirectoryUser.employee_id == OrgMeshPerson.employee_id),
        )
        .where(
            OrgMeshDirectoryUser.active.is_(True),
            OrgMeshDirectoryUser.expires_at > datetime.now(timezone.utc),
            ~disabled,
        )
    )


def _page_bounds(offset: int, limit: int) -> None:
    if not 0 <= offset <= 100000 or not 1 <= limit <= 100:
        raise ValueError("Invalid directory page bounds")


def _ordered(query: Select[tuple[OrgMeshPerson]]) -> Select[tuple[OrgMeshPerson]]:
    return query.order_by(
        func.lower(func.coalesce(OrgMeshPerson.display_name, "")),
        OrgMeshPerson.employee_id,
    )


def _profiles(db_session: Session, rows: list[OrgMeshPerson]) -> list[PersonProfile]:
    ids = [row.employee_id for row in rows]
    manager_ids = {row.manager_id for row in rows if row.manager_id is not None}
    visible_managers = (
        set(
            db_session.scalars(
                _visible_people()
                .with_only_columns(OrgMeshPerson.employee_id)
                .where(OrgMeshPerson.employee_id.in_(manager_ids))
            ).all()
        )
        if manager_ids
        else set()
    )
    departments: dict[str, list[DepartmentDisplay]] = {
        employee_id: [] for employee_id in ids
    }
    if ids:
        for employee_id, department in db_session.execute(
            select(OrgMeshPersonDepartment.employee_id, OrgMeshDepartment)
            .join(
                OrgMeshDepartment,
                OrgMeshDepartment.department_id
                == OrgMeshPersonDepartment.department_id,
            )
            .where(OrgMeshPersonDepartment.employee_id.in_(ids))
            .order_by(OrgMeshDepartment.name, OrgMeshDepartment.department_id)
        ):
            departments[employee_id].append(
                DepartmentDisplay(
                    department_id=department.department_id,
                    name=department.name,
                    parent_id=department.parent_id,
                )
            )
    return [
        PersonProfile(
            employee_id=row.employee_id,
            email=row.work_email,
            display_name=row.display_name,
            job_title=row.job_title,
            avatar_url=row.avatar_url,
            manager_id=row.manager_id if row.manager_id in visible_managers else None,
            direct_department_ids=[
                department.department_id for department in departments[row.employee_id]
            ],
            departments=departments[row.employee_id],
        )
        for row in rows
    ]


def list_people(
    db_session: Session,
    query: str = "",
    department_id: str | None = None,
    offset: int = 0,
    limit: int = 20,
) -> EmployeePage:
    _page_bounds(offset, limit)
    if len(query) > 200:
        raise ValueError("Directory search is too long")
    selection = _visible_people()
    if department_id is not None:
        selection = selection.where(
            exists(
                select(OrgMeshPersonDepartment.employee_id).where(
                    OrgMeshPersonDepartment.employee_id == OrgMeshPerson.employee_id,
                    OrgMeshPersonDepartment.department_id == department_id,
                )
            )
        )
    query = query.strip().lower()
    if query:
        match = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{match}%"
        team_match = exists(
            select(OrgMeshPersonDepartment.employee_id)
            .join(
                OrgMeshDepartment,
                OrgMeshDepartment.department_id
                == OrgMeshPersonDepartment.department_id,
            )
            .where(
                OrgMeshPersonDepartment.employee_id == OrgMeshPerson.employee_id,
                func.lower(OrgMeshDepartment.name).like(pattern, escape="\\"),
            )
        )
        selection = selection.where(
            or_(
                func.lower(OrgMeshPerson.display_name).like(pattern, escape="\\"),
                func.lower(OrgMeshPerson.work_email).like(pattern, escape="\\"),
                func.lower(OrgMeshPerson.job_title).like(pattern, escape="\\"),
                team_match,
            )
        )
    total = int(
        db_session.scalar(select(func.count()).select_from(selection.subquery())) or 0
    )
    rows = list(
        db_session.scalars(_ordered(selection).offset(offset).limit(limit)).all()
    )
    return EmployeePage(
        items=_profiles(db_session, rows), total=total, offset=offset, limit=limit
    )


def get_person(db_session: Session, employee_id: str) -> PersonProfile | None:
    row = db_session.scalars(
        _visible_people().where(OrgMeshPerson.employee_id == employee_id)
    ).first()
    return _profiles(db_session, [row])[0] if row is not None else None


def list_teams(db_session: Session, offset: int = 0, limit: int = 20) -> TeamPage:
    _page_bounds(offset, limit)
    visible = _visible_people().subquery()
    counts = (
        select(OrgMeshPersonDepartment.department_id, func.count().label("count"))
        .join(visible, visible.c.employee_id == OrgMeshPersonDepartment.employee_id)
        .group_by(OrgMeshPersonDepartment.department_id)
        .subquery()
    )
    selection = select(OrgMeshDepartment, counts.c.count).join(
        counts, counts.c.department_id == OrgMeshDepartment.department_id
    )
    total = int(
        db_session.scalar(select(func.count()).select_from(selection.subquery())) or 0
    )
    rows = db_session.execute(
        selection.order_by(
            func.lower(func.coalesce(OrgMeshDepartment.name, "")),
            OrgMeshDepartment.department_id,
        )
        .offset(offset)
        .limit(limit)
    ).all()
    return TeamPage(
        items=[
            TeamSummary(
                department_id=department.department_id,
                name=department.name,
                parent_id=department.parent_id,
                member_count=count,
            )
            for department, count in rows
        ],
        total=total,
        offset=offset,
        limit=limit,
    )


def get_team(
    db_session: Session, department_id: str, offset: int = 0, limit: int = 20
) -> TeamDetail | None:
    members = list_people(db_session, "", department_id, offset, limit)
    if not members.total:
        return None
    department = db_session.get(OrgMeshDepartment, department_id)
    if department is None:
        return None
    return TeamDetail(
        department_id=department.department_id,
        name=department.name,
        parent_id=department.parent_id,
        member_count=members.total,
        members=members,
    )


def get_relationships(
    db_session: Session, employee_id: str, offset: int = 0, limit: int = 20
) -> PersonRelationships | None:
    _page_bounds(offset, limit)
    row = db_session.scalars(
        _visible_people().where(OrgMeshPerson.employee_id == employee_id)
    ).first()
    if row is None:
        return None
    warnings: list[str] = []
    manager = get_person(db_session, row.manager_id) if row.manager_id else None
    if row.manager_id and manager is None:
        warnings.append("manager_unavailable")
    seen = {employee_id}
    current = manager
    for _ in range(64):
        if current is None:
            break
        if current.employee_id in seen:
            warnings.append("manager_cycle")
            manager = None
            break
        seen.add(current.employee_id)
        current = (
            get_person(db_session, current.manager_id) if current.manager_id else None
        )
    else:
        warnings.append("relationship_limit")
    selection = _visible_people().where(
        OrgMeshPerson.manager_id == employee_id,
        OrgMeshPerson.employee_id != employee_id,
    )
    total = int(
        db_session.scalar(select(func.count()).select_from(selection.subquery())) or 0
    )
    rows = list(
        db_session.scalars(_ordered(selection).offset(offset).limit(limit)).all()
    )
    return PersonRelationships(
        manager=manager,
        direct_reports=_profiles(db_session, rows),
        total_reports=total,
        offset=offset,
        limit=limit,
        warnings=warnings,
    )
