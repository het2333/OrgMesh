"""Run real People query/route code with isolated application boundaries.

Uses SQLite-compatible ORM column variants and a minimal native user table.
This does not prove PostgreSQL migrations, deployed auth, or tenant middleware.
The standard repository test command remains the full-environment gate.
"""

import ast
import datetime
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from fastapi import HTTPException
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "user"
    id: Mapped[UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(sa.String)
    is_active: Mapped[bool] = mapped_column(sa.Boolean, default=True)
    hashed_password: Mapped[str] = mapped_column(sa.String, default="test-only")
    is_verified: Mapped[bool] = mapped_column(sa.Boolean, default=True)
    prior_emails: Mapped[list[str]] = mapped_column(sa.JSON, default=list)


models = ModuleType("onyx.db.models")
models.Base = Base
models.User = User
sys.modules[models.__name__] = models
namespace = {
    "Base": Base,
    "Mapped": Mapped,
    "mapped_column": mapped_column,
    "datetime": datetime,
    "UUID": UUID,
    "uuid4": uuid4,
    "postgresql": SimpleNamespace(
        ARRAY=lambda kind: postgresql.ARRAY(kind).with_variant(sa.JSON(), "sqlite")
    ),
    **vars(sa),
}
source = ROOT / "backend/onyx/db/models.py"
tree = ast.parse(source.read_text())
for name in (
    "OrgMeshDirectoryUser",
    "OrgMeshPerson",
    "OrgMeshDepartment",
    "OrgMeshPersonDepartment",
):
    declaration = next(
        (
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == name
        ),
        None,
    )
    if declaration is not None:
        exec(  # noqa: S102 — evaluate reviewed local model declarations
            compile(
                ast.Module(body=[declaration], type_ignores=[]), str(source), "exec"
            ),
            namespace,
        )
        setattr(models, name, namespace[name])

from onyx.access.people_models import DirectorySnapshot  # noqa: E402

orgmesh = ModuleType("onyx.db.orgmesh")
sys.modules[orgmesh.__name__] = orgmesh
orgmesh_source = ROOT / "backend/onyx/db/orgmesh.py"
orgmesh_tree = ast.parse(orgmesh_source.read_text())
orgmesh_decls = [
    node
    for node in orgmesh_tree.body
    if isinstance(node, ast.FunctionDef)
    and node.name in ("replace_directory_snapshot", "_replace_directory_memberships")
]
vars(orgmesh).update(
    {
        **vars(sa),
        **vars(models),
        "Session": Session,
        "datetime": datetime.datetime,
        "timezone": datetime.timezone,
        "timedelta": datetime.timedelta,
        "insert": postgresql.insert,
        "DirectorySnapshot": DirectorySnapshot,
        "ACL_MAX_AGE_SECONDS": 900,
        "SQLAlchemyError": sa.exc.SQLAlchemyError,
    }
)
exec(  # noqa: S102 — evaluate reviewed local model declarations
    compile(
        ast.Module(body=orgmesh_decls, type_ignores=[]), str(orgmesh_source), "exec"
    ),
    vars(orgmesh),
)

permissions = ModuleType("onyx.auth.permissions")


def auth_boundary():
    raise HTTPException(401)


permissions.require_permission = lambda _permission: auth_boundary
sys.modules[permissions.__name__] = permissions
engine_module = ModuleType("onyx.db.engine.sql_engine")
engine_module.get_session = lambda: None
sys.modules[engine_module.__name__] = engine_module
directory_routes = ModuleType("onyx.server.orgmesh")
directory_routes.load_directory_config = lambda: SimpleNamespace(enabled=True)
sys.modules[directory_routes.__name__] = directory_routes


class Fixtures:
    @pytest.fixture
    def db_session(self):
        engine = sa.create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=sa.pool.StaticPool,
        )

        @sa.event.listens_for(engine, "connect")
        def register_lock(connection, _record):
            connection.create_function("pg_advisory_xact_lock", 1, lambda _key: 0)

        Base.metadata.create_all(engine)
        with Session(engine) as session:
            yield session
        engine.dispose()


if __name__ == "__main__":
    paths = sys.argv[1:] or [
        "backend/tests/external_dependency_unit/orgmesh/test_people.py"
    ]
    raise SystemExit(
        pytest.main(
            ["--noconftest", "-o", "filterwarnings=", "-q", *paths],
            plugins=[Fixtures()],
        )
    )
