"""Authenticated, read-only employee, team and relationship routes."""

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy.orm import Session

from onyx.access.people_models import (
    EmployeePage,
    PersonProfile,
    PersonRelationships,
    TeamDetail,
    TeamPage,
)
from onyx.auth.permissions import require_permission
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import Permission
from onyx.db.models import User
from onyx.db.people import (
    get_person,
    get_relationships,
    get_team,
    list_people,
    list_teams,
)
from onyx.server.orgmesh import load_directory_config

router = APIRouter(prefix="/orgmesh")
people_user = require_permission(Permission.BASIC_ACCESS)


@router.get("/people")
def employees(
    q: str = Query(default="", max_length=200),
    department_id: str | None = Query(default=None, min_length=1, max_length=200),
    offset: int = Query(default=0, ge=0, le=100000),
    limit: int = Query(default=20, ge=1, le=100),
    _: User = Depends(people_user),
    db_session: Session = Depends(get_session),
) -> EmployeePage:
    if not load_directory_config().enabled:
        return EmployeePage(items=[], total=0, offset=offset, limit=limit)
    return list_people(db_session, q, department_id, offset, limit)


@router.get("/people/{employee_id}")
def profile(
    employee_id: str = Path(min_length=1, max_length=200),
    _: User = Depends(people_user),
    db_session: Session = Depends(get_session),
) -> PersonProfile:
    person = (
        get_person(db_session, employee_id) if load_directory_config().enabled else None
    )
    if person is None:
        raise HTTPException(status_code=404, detail="Person is unavailable")
    return person


@router.get("/people/{employee_id}/relationships")
def relationships(
    employee_id: str = Path(min_length=1, max_length=200),
    offset: int = Query(default=0, ge=0, le=100000),
    limit: int = Query(default=20, ge=1, le=100),
    _: User = Depends(people_user),
    db_session: Session = Depends(get_session),
) -> PersonRelationships:
    result = (
        get_relationships(db_session, employee_id, offset, limit)
        if load_directory_config().enabled
        else None
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Person is unavailable")
    return result


@router.get("/teams")
def teams(
    offset: int = Query(default=0, ge=0, le=100000),
    limit: int = Query(default=20, ge=1, le=100),
    _: User = Depends(people_user),
    db_session: Session = Depends(get_session),
) -> TeamPage:
    if not load_directory_config().enabled:
        return TeamPage(items=[], total=0, offset=offset, limit=limit)
    return list_teams(db_session, offset, limit)


@router.get("/teams/{department_id}")
def team(
    department_id: str = Path(min_length=1, max_length=200),
    offset: int = Query(default=0, ge=0, le=100000),
    limit: int = Query(default=20, ge=1, le=100),
    _: User = Depends(people_user),
    db_session: Session = Depends(get_session),
) -> TeamDetail:
    result = (
        get_team(db_session, department_id, offset, limit)
        if load_directory_config().enabled
        else None
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Team is unavailable")
    return result
