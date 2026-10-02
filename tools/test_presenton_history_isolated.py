"""Run history tests with real SQLAlchemy and isolated application boundaries.

This runner loads the new ORM declarations from models.py unchanged. It replaces
unrelated application imports and runs SQLite tests. It does not prove PostgreSQL
migration behavior, full application startup, tenant routing, or live editor flows.
Use the normal repository pytest command for full-environment verification.
"""

import ast
import asyncio
import datetime
import os
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Literal
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field, JsonValue
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


class Base(DeclarativeBase):
    pass


def module(name: str) -> ModuleType:
    result = ModuleType(name)
    sys.modules[name] = result
    return result


models = module("onyx.db.models")
models.Base = Base
for name, kind in [
    ("user", PGUUID(as_uuid=True)),
    ("chat_session", PGUUID(as_uuid=True)),
    ("user_project", sa.Integer()),
]:
    sa.Table(name, Base.metadata, sa.Column("id", kind, primary_key=True))
namespace = {
    "Base": Base,
    "UUID": UUID,
    "uuid4": uuid4,
    "datetime": datetime,
    "Mapped": Mapped,
    "mapped_column": mapped_column,
    "PGUUID": PGUUID,
    **{
        name: vars(sa)[name]
        for name in (
            "String",
            "Boolean",
            "text",
            "ForeignKey",
            "DateTime",
            "CheckConstraint",
            "UniqueConstraint",
            "Index",
            "Integer",
            "Text",
            "func",
        )
    },
}
source = ROOT / "backend/onyx/db/models.py"
tree = ast.parse(source.read_text())
for name in ("PresentationTask", "PresentationRecord"):
    declaration = next(
        (
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == name
        ),
        None,
    )
    if declaration is None:
        raise AssertionError(f"Missing production ORM model: {name}")
    exec(  # noqa: S102 — run reviewed local declarations
        compile(ast.Module(body=[declaration], type_ignores=[]), str(source), "exec"),
        namespace,
    )  # noqa: S102 — run reviewed model declarations
    setattr(models, name, namespace[name])


# Source authorization runs in the real application. Tests mock these boundaries.
def unavailable(*_args: object, **_kwargs: object) -> object:
    raise AssertionError("Application boundary must be mocked in isolated tests")


module("onyx.db.chat").get_chat_session_by_id = unavailable
module("onyx.db.projects").check_project_ownership = unavailable
# Load the real error class without its application logger/FastAPI imports.
errors = module("onyx.error_handling.exceptions")
error_source = ROOT / "backend/onyx/error_handling/exceptions.py"
error_tree = ast.parse(error_source.read_text())
error_decl = next(
    node
    for node in error_tree.body
    if isinstance(node, ast.ClassDef) and node.name == "OnyxError"
)
from onyx.error_handling.error_codes import OnyxErrorCode  # noqa: E402

errors.OnyxErrorCode = OnyxErrorCode
exec(  # noqa: S102 — run reviewed local declarations
    compile(ast.Module(body=[error_decl], type_ignores=[]), str(error_source), "exec"),
    vars(errors),
)  # noqa: S102 — run reviewed error declaration
# Load the exact changed routes, with unrelated auth/model/network dependencies mocked.
from onyx.db import presentation_history  # noqa: E402 — boundaries prepared above
from onyx.presentation_history.contract import HistoryQuery  # noqa: E402
from onyx.presentation_history.routing import read_history_response  # noqa: E402

routes = module("onyx.server.presenton")


def user_boundary() -> None:
    raise AssertionError("Authentication boundary must be mocked")


def db_boundary() -> None:
    raise AssertionError("Database boundary must be mocked")


vars(routes).update(
    {
        "asyncio": asyncio,
        "os": os,
        "datetime": datetime.datetime,
        "timezone": datetime.timezone,
        "UUID": UUID,
        "Literal": Literal,
        "BaseModel": BaseModel,
        "ConfigDict": ConfigDict,
        "Field": Field,
        "JsonValue": JsonValue,
        "Session": Session,
        "HistoryQuery": HistoryQuery,
        "read_history_response": read_history_response,
        "APIRouter": APIRouter,
        "Depends": Depends,
        "Query": Query,
        "User": SimpleNamespace,
        "Permission": SimpleNamespace(BASIC_ACCESS="basic"),
        "require_permission": lambda _permission: user_boundary,
        "get_session": db_boundary,
        "OnyxError": errors.OnyxError,
        "OnyxErrorCode": OnyxErrorCode,
        "SQLAlchemyError": SQLAlchemyError,
        "presentation_model": unavailable,
        "_json": unavailable,
        "router": APIRouter(prefix="/orgmesh/presenton"),
        "_generation_lock": asyncio.Lock(),
        **{
            name: vars(presentation_history)[name]
            for name in (
                "fail_generation",
                "history_facts_for_owner",
                "link_generation",
                "reserve_generation",
                "sync_jobs",
                "sync_presentations",
                "validate_source",
            )
        },
    }
)
route_source = ROOT / "backend/onyx/server/presenton.py"
route_names = {
    "_normalize_dates",
    "_history_enabled",
    "history",
    "presentations",
    "jobs",
    "GeneratePresentation",
    "GenerationJob",
    "generate",
}
route_tree = ast.parse(route_source.read_text())
selected = [
    node
    for node in route_tree.body
    if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    and node.name in route_names
]
exec(  # noqa: S102 — run reviewed local declarations
    compile(ast.Module(body=selected, type_ignores=[]), str(route_source), "exec"),
    vars(routes),
)  # noqa: S102 — run reviewed route declarations
raise SystemExit(
    pytest.main(
        [
            "--confcutdir=" + str(ROOT / "backend/tests/unit/orgmesh"),
            "-c",
            "/dev/null",
            str(ROOT / "backend/tests/unit/orgmesh/test_presentation_history.py"),
            str(
                ROOT / "backend/tests/unit/orgmesh/test_presentation_history_routes.py"
            ),
            str(
                ROOT / "backend/tests/unit/orgmesh/test_history_projection_contract.py"
            ),
            str(ROOT / "backend/tests/unit/orgmesh/test_history_go_routing.py"),
            str(ROOT / "backend/tests/unit/orgmesh/test_history_go_packaging.py"),
            "-q",
        ]
    )
)
