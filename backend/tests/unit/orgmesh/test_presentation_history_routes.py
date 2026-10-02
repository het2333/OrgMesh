"""Route contract tests with the engine and application model boundary mocked."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from onyx.db.models import Base, PresentationRecord, PresentationTask
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server import presenton


@pytest.fixture
def db() -> Session:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(
        engine, tables=[PresentationTask.__table__, PresentationRecord.__table__]
    )
    with Session(engine) as session:
        yield session
    engine.dispose()


@pytest.mark.parametrize("endpoint", ["jobs", "presentations"])
def test_disabled_flag_keeps_original_list_shape(
    db: Session, monkeypatch: pytest.MonkeyPatch, endpoint: str
) -> None:
    monkeypatch.delenv("ORGMESH_PRESENTON_HISTORY_ENABLED", raising=False)
    owner = SimpleNamespace(id=uuid4())
    payload = [
        {"id": str(uuid4()), "status": "pending", "created_at": "2025-09-01T12:00:00Z"}
    ]
    with patch.object(presenton, "_json", AsyncMock(return_value=payload)):
        result = asyncio.run(vars(presenton)[endpoint](owner, db))
    assert result == payload
    assert not db.query(PresentationTask).count()


def test_generate_disabled_response_and_payload_unchanged(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ORGMESH_PRESENTON_HISTORY_ENABLED", raising=False)
    owner, task_id = SimpleNamespace(id=uuid4()), str(uuid4())
    engine = AsyncMock(side_effect=[[], {"id": task_id}])
    with (
        patch.object(presenton, "_json", engine),
        patch.object(presenton, "presentation_model"),
    ):
        result = asyncio.run(
            presenton.generate(
                presenton.GeneratePresentation(content="Test content"), owner, db
            )
        )
    assert result.model_dump() == {"task_id": task_id}
    payload = engine.call_args.args[3]
    assert "project_id" not in payload
    assert "source_chat_id" not in payload
    assert payload["language"] == "Chinese"
    assert payload["export_as"] == "pptx"


def test_generate_saves_platform_source_without_forwarding_it(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ORGMESH_PRESENTON_HISTORY_ENABLED", "true")
    owner, source, engine_id = SimpleNamespace(id=uuid4()), uuid4(), str(uuid4())
    chat = SimpleNamespace(
        user_id=owner.id, deleted=False, incognito_record_mode=None, project_id=7
    )
    engine = AsyncMock(side_effect=[[], {"id": engine_id}])
    with (
        patch.object(presenton, "_json", engine),
        patch.object(presenton, "presentation_model") as model,
        patch("onyx.db.presentation_history.get_chat_session_by_id", return_value=chat),
        patch(
            "onyx.db.presentation_history.check_project_ownership", return_value=True
        ),
    ):
        result = asyncio.run(
            presenton.generate(
                presenton.GeneratePresentation(
                    content="Content", source_chat_id=source
                ),
                owner,
                db,
            )
        )
    task = db.query(PresentationTask).one()
    assert result == {"task_id": engine_id, "platform_task_id": str(task.id)}
    assert task.source_chat_id == source
    assert task.project_id == 7
    assert task.status == "pending"
    assert task.engine_task_id == UUID(engine_id)
    assert "source_chat_id" not in engine.call_args.args[3]
    assert "project_id" not in engine.call_args.args[3]
    model.assert_called_once_with(db, owner)


def test_bad_source_rejected_before_engine_call(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ORGMESH_PRESENTON_HISTORY_ENABLED", "true")
    owner = SimpleNamespace(id=uuid4())
    chat = SimpleNamespace(
        user_id=owner.id,
        deleted=False,
        incognito_record_mode="full_history",
        project_id=None,
    )
    engine = AsyncMock()
    with (
        patch.object(presenton, "_json", engine),
        patch.object(presenton, "presentation_model"),
        patch("onyx.db.presentation_history.get_chat_session_by_id", return_value=chat),
        pytest.raises(OnyxError),
    ):
        asyncio.run(
            presenton.generate(
                presenton.GeneratePresentation(
                    content="Content", source_chat_id=uuid4()
                ),
                owner,
                db,
            )
        )
    engine.assert_not_called()
    assert db.query(PresentationTask).count() == 0


def test_engine_failure_records_failed_attempt(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ORGMESH_PRESENTON_HISTORY_ENABLED", "true")
    owner = SimpleNamespace(id=uuid4())
    engine = AsyncMock(
        side_effect=[[], OnyxError(OnyxErrorCode.BAD_GATEWAY, status_code_override=400)]
    )
    with (
        patch.object(presenton, "_json", engine),
        patch.object(presenton, "presentation_model"),
        pytest.raises(OnyxError),
    ):
        asyncio.run(
            presenton.generate(
                presenton.GeneratePresentation(content="Content"), owner, db
            )
        )
    task = db.query(PresentationTask).one()
    assert task.status == "error"
    assert task.engine_task_id is None


def test_history_is_owner_scoped_and_does_not_call_engine(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from onyx.db.presentation_history import reserve_generation

    monkeypatch.setenv("ORGMESH_PRESENTON_HISTORY_ENABLED", "true")
    owner = SimpleNamespace(id=uuid4())
    reserve_generation(db, owner.id, None, None)
    reserve_generation(db, uuid4(), None, None)
    with patch.object(presenton, "_json", AsyncMock()) as engine:
        result = asyncio.run(presenton.history(50, 0, owner, db, None))
    assert len(result) == 1
    engine.assert_not_called()


def test_disabled_history_rejects_links_and_history_route(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ORGMESH_PRESENTON_HISTORY_ENABLED", raising=False)
    owner = SimpleNamespace(id=uuid4())
    with patch.object(presenton, "presentation_model"), pytest.raises(OnyxError):
        asyncio.run(
            presenton.generate(
                presenton.GeneratePresentation(content="Content", project_id=7),
                owner,
                db,
            )
        )
    with pytest.raises(OnyxError):
        asyncio.run(presenton.history(50, 0, owner, db, None))


def test_http_pagination_rejects_invalid_limits() -> None:
    app = FastAPI()
    app.include_router(presenton.router)
    for route in presenton.router.routes:
        if route.path.endswith("/history"):
            for dependency in route.dependant.dependencies:
                app.dependency_overrides[dependency.call] = lambda: SimpleNamespace(
                    id=uuid4()
                )
    with TestClient(app) as client:
        for query in [
            "limit=0",
            "limit=101",
            "offset=-1",
            "offset=100001",
            "status=not-a-status",
        ]:
            assert client.get("/orgmesh/presenton/history?" + query).status_code == 422


def test_http_generate_serialization_retains_platform_id(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ORGMESH_PRESENTON_HISTORY_ENABLED", "true")
    owner, engine_id = SimpleNamespace(id=uuid4()), str(uuid4())
    app = FastAPI()
    app.include_router(presenton.router)
    for route in presenton.router.routes:
        if route.path.endswith("/generate"):
            for dependency in route.dependant.dependencies:
                if dependency.name == "user":
                    app.dependency_overrides[dependency.call] = lambda: owner
                if dependency.name == "db_session":
                    app.dependency_overrides[dependency.call] = lambda: db
    with (
        patch.object(
            presenton, "_json", AsyncMock(side_effect=[[], {"id": engine_id}])
        ),
        patch.object(presenton, "presentation_model"),
        TestClient(app) as client,
    ):
        response = client.post(
            "/orgmesh/presenton/generate", json={"content": "Test content"}
        )
    assert response.status_code == 200
    assert response.json()["task_id"] == engine_id
    assert response.json()["platform_task_id"] == str(
        db.query(PresentationTask).one().id
    )


def test_uncertain_engine_outcome_stays_unresolved_and_warns(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ORGMESH_PRESENTON_HISTORY_ENABLED", "true")
    owner = SimpleNamespace(id=uuid4())
    engine = AsyncMock(side_effect=[[], OnyxError(OnyxErrorCode.SERVICE_UNAVAILABLE)])
    with (
        patch.object(presenton, "_json", engine),
        patch.object(presenton, "presentation_model"),
        pytest.raises(OnyxError) as error,
    ):
        asyncio.run(
            presenton.generate(
                presenton.GeneratePresentation(content="Content"), owner, db
            )
        )
    task = db.query(PresentationTask).one()
    assert task.status == "submitting"
    assert "Check jobs before retrying" in error.value.detail
    assert error.value.extra["platform_task_id"] == str(task.id)


def test_transient_db_bind_failure_retries_only_database(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from unittest.mock import DEFAULT, Mock

    from sqlalchemy.exc import OperationalError

    monkeypatch.setenv("ORGMESH_PRESENTON_HISTORY_ENABLED", "true")
    owner, engine_id = SimpleNamespace(id=uuid4()), str(uuid4())
    engine = AsyncMock(side_effect=[[], {"id": engine_id}])
    link = Mock(
        wraps=presenton.link_generation,
        side_effect=[OperationalError("bind", {}, Exception("temporary")), DEFAULT],
    )
    with (
        patch.object(presenton, "_json", engine),
        patch.object(presenton, "presentation_model"),
        patch.object(presenton, "link_generation", link),
    ):
        result = asyncio.run(
            presenton.generate(
                presenton.GeneratePresentation(content="Content"), owner, db
            )
        )
    assert result["task_id"] == engine_id
    assert db.query(PresentationTask).one().status == "pending"
    assert db.query(PresentationTask).one().engine_task_id == UUID(engine_id)
    assert link.call_count == 2
    assert sum(call.args[1] == "POST" for call in engine.call_args_list) == 1


def test_persistent_db_bind_failure_returns_accepted_job_and_sync_warning(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlalchemy.exc import OperationalError

    monkeypatch.setenv("ORGMESH_PRESENTON_HISTORY_ENABLED", "true")
    owner, engine_id = SimpleNamespace(id=uuid4()), str(uuid4())
    engine = AsyncMock(side_effect=[[], {"id": engine_id}])
    with (
        patch.object(presenton, "_json", engine),
        patch.object(presenton, "presentation_model"),
        patch.object(
            presenton,
            "link_generation",
            side_effect=OperationalError("bind", {}, Exception("offline")),
        ) as link,
    ):
        result = asyncio.run(
            presenton.generate(
                presenton.GeneratePresentation(content="Content"), owner, db
            )
        )
    assert result["task_id"] == engine_id
    assert result["history_status"] == "awaiting_sync"
    assert result["platform_task_id"] == str(db.query(PresentationTask).one().id)
    assert db.query(PresentationTask).one().status == "submitting"
    assert link.call_count == 2
    assert sum(call.args[1] == "POST" for call in engine.call_args_list) == 1
