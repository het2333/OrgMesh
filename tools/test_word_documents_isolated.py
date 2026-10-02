"""Run real Word route, ORM, validation and DB tests with isolated boundaries.

Auth and file-store I/O use test boundaries. SQLite runs the real ORM and queries.
This does not prove live auth, tenant schema routing, PostgreSQL locks/migrations,
production object storage, full application startup, or browser DOCX fidelity.
"""

import ast
import datetime
import sys
from enum import Enum
from pathlib import Path
from types import ModuleType, SimpleNamespace
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def module(name):
    result = ModuleType(name)
    sys.modules[name] = result
    return result


def declaration(path, names, namespace):
    tree = ast.parse(path.read_text())
    nodes = [
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name in names
    ]
    assert {node.name for node in nodes} == set(names), (
        f"Missing production declarations: {names}"
    )
    exec(  # noqa: S102 — run reviewed local declarations
        compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), namespace
    )


class Base(DeclarativeBase):
    pass


models = module("onyx.db.models")
models.Base = Base
models.User = SimpleNamespace
sa.Table("user", Base.metadata, sa.Column("id", PGUUID(as_uuid=True), primary_key=True))
sa.Table(
    "file_record",
    Base.metadata,
    sa.Column("file_id", sa.String, primary_key=True),
    sa.Column("file_origin", sa.String),
)
namespace = {
    "Base": Base,
    "UUID": UUID,
    "uuid4": uuid4,
    "datetime": datetime,
    "Mapped": Mapped,
    "mapped_column": mapped_column,
    "PGUUID": PGUUID,
    **vars(sa),
}
declaration(
    ROOT / "backend/onyx/db/models.py",
    ["WordDocument", "WordDocumentVersion"],
    namespace,
)
models.WordDocument = namespace["WordDocument"]
models.WordDocumentVersion = namespace["WordDocumentVersion"]


class FileRecord(Base):
    __table__ = Base.metadata.tables["file_record"]


models.FileRecord = FileRecord
constants = module("onyx.configs.constants")
constants.Enum = Enum
declaration(ROOT / "backend/onyx/configs/constants.py", ["FileOrigin"], vars(constants))
models.FileRecord.__table__.c.file_origin.type = sa.Enum(
    constants.FileOrigin, native_enum=False
)
from onyx.error_handling.error_codes import OnyxErrorCode  # noqa: E402

errors = module("onyx.error_handling.exceptions")
errors.OnyxErrorCode = OnyxErrorCode
declaration(
    ROOT / "backend/onyx/error_handling/exceptions.py", ["OnyxError"], vars(errors)
)


def unavailable(*_args, **_kwargs):
    raise AssertionError("Application boundary must be replaced by a test fixture")


def auth_unavailable():
    raise AssertionError("Authentication must be replaced by a test fixture")


module("onyx.auth.permissions").require_permission = lambda _: auth_unavailable
module("onyx.db.enums").Permission = SimpleNamespace(BASIC_ACCESS="basic")
module("onyx.db.engine.sql_engine").get_session = unavailable
module("onyx.file_store.file_store").get_default_file_store = unavailable
raise SystemExit(
    pytest.main(
        [
            "--confcutdir=" + str(ROOT / "backend/tests/unit/orgmesh"),
            "-c",
            "/dev/null",
            str(ROOT / "backend/tests/unit/orgmesh/test_word_documents.py"),
            "-q",
            *sys.argv[1:],
        ]
    )
)
