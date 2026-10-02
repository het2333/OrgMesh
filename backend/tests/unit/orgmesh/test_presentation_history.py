"""Focused persistence tests. These do not need a running Presenton service."""

from datetime import datetime, timezone
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from onyx.db.models import Base, PresentationRecord, PresentationTask
from onyx.db.presentation_history import (
    history_for_owner,
    link_generation,
    reserve_generation,
    sync_jobs,
    sync_presentations,
    validate_source,
)
from onyx.error_handling.exceptions import OnyxError


@pytest.fixture
def db() -> Session:
    engine = create_engine("sqlite://")
    # Only history tables. Ownership and source services are mocked below.
    Base.metadata.create_all(
        engine, tables=[PresentationTask.__table__, PresentationRecord.__table__]
    )
    with Session(engine) as session:
        yield session
    engine.dispose()


def test_repeat_sync_is_idempotent_and_owner_scoped(db: Session) -> None:
    owner, other, engine_id = uuid4(), uuid4(), uuid4()
    jobs = [{"id": str(engine_id), "status": "pending"}]
    first = sync_jobs(db, owner, jobs)
    again = sync_jobs(db, owner, jobs)
    second = sync_jobs(db, other, jobs)
    assert first[0]["platform_task_id"] == again[0]["platform_task_id"]
    assert second[0]["platform_task_id"] != first[0]["platform_task_id"]
    assert len(history_for_owner(db, owner, 50, 0)) == 1
    assert len(list(db.scalars(select(PresentationTask)))) == 2


def test_completion_preserves_source_and_does_not_regress(db: Session) -> None:
    owner, source, engine_task, engine_deck = uuid4(), uuid4(), uuid4(), uuid4()
    task = reserve_generation(db, owner, 9, source)
    link_generation(db, owner, task.id, engine_task)
    completed = [
        {
            "id": str(engine_task),
            "status": "completed",
            "data": {"presentation_id": str(engine_deck)},
        }
    ]
    with patch("onyx.db.presentation_history.visible_source", return_value=(9, source)):
        sync_jobs(db, owner, completed)
        sync_jobs(db, owner, [{"id": str(engine_task), "status": "pending"}])
        rows = sync_presentations(
            db, owner, [{"id": str(engine_deck), "title": "Deck"}]
        )
        history = history_for_owner(db, owner, 50, 0)
    assert history[0]["status"] == "completed"
    assert history[0]["platform_task_id"] == str(task.id)
    assert history[0]["presentation_id"] == str(engine_deck)
    assert rows[0]["source_chat_id"] == str(source)
    assert rows[0]["project_id"] == 9
    assert len(list(db.scalars(select(PresentationRecord)))) == 1


def test_legacy_presentation_has_no_invented_source(db: Session) -> None:
    owner, deck = uuid4(), uuid4()
    row = sync_presentations(db, owner, [{"id": str(deck), "title": "Legacy"}])[0]
    assert row["source_chat_id"] is None
    assert row["project_id"] is None
    assert row["platform_task_id"] is None
    assert row["id"] == str(deck)


def test_library_before_completed_job_links_same_record(db: Session) -> None:
    owner, deck, engine_task = uuid4(), uuid4(), uuid4()
    imported = sync_presentations(db, owner, [{"id": str(deck)}])[0]
    task = reserve_generation(db, owner, None, None)
    link_generation(db, owner, task.id, engine_task)
    sync_jobs(
        db,
        owner,
        [
            {
                "id": str(engine_task),
                "status": "completed",
                "data": {"presentation_id": str(deck)},
            }
        ],
    )
    again = sync_presentations(db, owner, [{"id": str(deck)}])[0]
    assert again["platform_presentation_id"] == imported["platform_presentation_id"]
    assert again["platform_task_id"] == str(task.id)


def test_pagination_is_bounded_and_durable_without_engine(db: Session) -> None:
    owner = uuid4()
    for _ in range(3):
        reserve_generation(db, owner, None, None)
    assert len(history_for_owner(db, owner, 2, 0)) == 2
    assert len(history_for_owner(db, owner, 2, 2)) == 1
    assert history_for_owner(db, uuid4(), 50, 0) == []


@pytest.mark.parametrize("bad_status", [None, "running", 4])
def test_unknown_engine_status_rejected_without_partial_writes(
    db: Session, bad_status: object
) -> None:
    with pytest.raises(OnyxError):
        sync_jobs(db, uuid4(), [{"id": str(uuid4()), "status": bad_status}])
    assert not list(db.scalars(select(PresentationTask)))


def test_original_created_date_and_response_keys_retained(db: Session) -> None:
    owner, task = uuid4(), uuid4()
    date = "2025-09-01T12:00:00Z"
    result = sync_jobs(
        db,
        owner,
        [
            {
                "id": str(task),
                "status": "pending",
                "created_at": date,
                "message": "upstream",
            }
        ],
    )
    assert result[0]["created_at"] == date
    assert result[0]["message"] == "upstream"
    assert datetime.fromisoformat(
        history_for_owner(db, owner, 50, 0)[0]["created_at"]
    ).replace(tzinfo=timezone.utc) == datetime.fromisoformat(date)


@pytest.mark.parametrize(
    "foreign,deleted,incognito",
    [(True, False, None), (False, True, None), (False, False, "full_history")],
)
def test_source_rejects_foreign_deleted_and_incognito(
    db: Session, foreign: bool, deleted: bool, incognito: str | None
) -> None:
    from types import SimpleNamespace

    owner, source = uuid4(), uuid4()
    chat = SimpleNamespace(
        user_id=uuid4() if foreign else owner,
        deleted=deleted,
        incognito_record_mode=incognito,
        project_id=None,
    )
    with (
        patch("onyx.db.presentation_history.get_chat_session_by_id", return_value=chat),
        pytest.raises(OnyxError),
    ):
        validate_source(db, owner, None, source)


def test_source_uses_existing_acl_and_owned_project(db: Session) -> None:
    from types import SimpleNamespace

    owner, source = uuid4(), uuid4()
    chat = SimpleNamespace(
        user_id=owner, deleted=False, incognito_record_mode=None, project_id=7
    )
    with (
        patch(
            "onyx.db.presentation_history.get_chat_session_by_id", return_value=chat
        ) as loader,
        patch(
            "onyx.db.presentation_history.check_project_ownership", return_value=True
        ),
    ):
        assert validate_source(db, owner, None, source) == (7, source)
        loader.assert_called_once_with(source, owner, db)
    with (
        patch("onyx.db.presentation_history.get_chat_session_by_id", return_value=chat),
        pytest.raises(OnyxError),
    ):
        validate_source(db, owner, 8, source)
    with (
        patch(
            "onyx.db.presentation_history.check_project_ownership", return_value=False
        ),
        pytest.raises(OnyxError),
    ):
        validate_source(db, owner, 8, None)


def test_revoked_source_hidden_in_history_without_deleting_task(db: Session) -> None:
    owner, source = uuid4(), uuid4()
    task = reserve_generation(db, owner, None, source)
    with patch(
        "onyx.db.presentation_history.get_chat_session_by_id",
        side_effect=ValueError("revoked"),
    ):
        row = history_for_owner(db, owner, 50, 0)[0]
    assert row["source_chat_id"] is None
    assert db.get(PresentationTask, task.id).source_chat_id == source


def test_stale_poll_returns_terminal_status_and_deck(db: Session) -> None:
    owner, task, deck = uuid4(), uuid4(), uuid4()
    sync_jobs(
        db,
        owner,
        [
            {
                "id": str(task),
                "status": "completed",
                "data": {"presentation_id": str(deck)},
            }
        ],
    )
    result = sync_jobs(
        db, owner, [{"id": str(task), "status": "pending", "data": None}]
    )[0]
    assert result["status"] == "completed"
    assert result["data"]["presentation_id"] == str(deck)


def test_failed_submission_stays_in_owner_history(db: Session) -> None:
    from onyx.db.presentation_history import fail_generation

    owner = uuid4()
    task = reserve_generation(db, owner, None, None)
    fail_generation(db, owner, task.id)
    row = history_for_owner(db, owner, 50, 0)[0]
    assert row["status"] == "error"
    assert row["task_id"] is None


def test_migration_matches_orm_and_renders_postgres_sql() -> None:
    import importlib.util
    from io import StringIO
    from pathlib import Path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import MetaData
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.schema import CreateTable

    path = (
        Path(__file__).resolve().parents[3]
        / "alembic/versions/b4c91a7e2d60_add_orgmesh_presentation_history.py"
    )
    spec = importlib.util.spec_from_file_location("history_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    metadata = MetaData()
    for name in ("user", "chat_session", "user_project"):
        Base.metadata.tables[name].to_metadata(metadata)

    def capture_table(name, *columns):
        from sqlalchemy import Table

        return Table(name, metadata, *columns)

    with (
        patch.object(migration.op, "create_table", side_effect=capture_table),
        patch.object(migration.op, "create_index"),
    ):
        migration.upgrade()
    for model in (PresentationTask, PresentationRecord):
        table = metadata.tables[model.__tablename__]
        assert set(table.columns.keys()) == set(model.__table__.columns.keys())
        for column in table.columns:
            expected = model.__table__.columns[column.name]
            assert column.nullable == expected.nullable
            assert str(column.type.compile(dialect=postgresql.dialect())) == str(
                expected.type.compile(dialect=postgresql.dialect())
            )
        assert {str(c.sqltext) for c in table.constraints if hasattr(c, "sqltext")} == {
            str(c.sqltext) for c in model.__table__.constraints if hasattr(c, "sqltext")
        }
        assert str(CreateTable(table).compile(dialect=postgresql.dialect()))
    output = StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output}
    )
    with Operations.context(context):
        migration.upgrade()
    assert "CREATE TABLE orgmesh_presentation_task" in output.getvalue()
    assert "ON DELETE SET NULL" in output.getvalue()
    assert migration.down_revision == "8266b8886041"


def test_poll_before_link_merges_import_into_reserved_source_task(db: Session) -> None:
    owner, source, engine_task, deck = uuid4(), uuid4(), uuid4(), uuid4()
    reserved = reserve_generation(db, owner, None, source)
    # A second request observes the engine job before POST finishes its DB bind.
    sync_jobs(
        db,
        owner,
        [
            {
                "id": str(engine_task),
                "status": "completed",
                "data": {"presentation_id": str(deck)},
            }
        ],
    )
    link_generation(db, owner, reserved.id, engine_task)
    tasks = list(db.scalars(select(PresentationTask)))
    assert len(tasks) == 1
    assert tasks[0].id == reserved.id
    assert tasks[0].source_chat_id == source
    assert tasks[0].status == "completed"
    assert tasks[0].presentation_id == deck
    assert db.scalars(select(PresentationRecord)).one().task_id == reserved.id


def test_second_generation_cannot_claim_already_bound_engine_job(db: Session) -> None:
    owner, engine_task = uuid4(), uuid4()
    first = reserve_generation(db, owner, None, None)
    link_generation(db, owner, first.id, engine_task)
    second = reserve_generation(db, owner, None, None)
    with pytest.raises(OnyxError):
        link_generation(db, owner, second.id, engine_task)
    assert db.get(PresentationTask, first.id).engine_task_id == engine_task


def test_status_filter_is_owner_scoped_and_applied_before_pagination(
    db: Session,
) -> None:
    from onyx.db.presentation_history import fail_generation

    owner = uuid4()
    reserve_generation(db, owner, None, None)
    failed = reserve_generation(db, owner, None, None)
    fail_generation(db, owner, failed.id)
    another_owner = uuid4()
    other_failed = reserve_generation(db, another_owner, None, None)
    fail_generation(db, another_owner, other_failed.id)
    rows = history_for_owner(db, owner, 1, 0, "error")
    assert len(rows) == 1
    assert rows[0]["platform_task_id"] == str(failed.id)
    assert history_for_owner(db, owner, 1, 1, "error") == []
