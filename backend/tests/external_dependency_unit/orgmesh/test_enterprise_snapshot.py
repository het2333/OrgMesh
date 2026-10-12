"""Use isolated PostgreSQL schemas to verify the read-only source adapter."""

import importlib
import importlib.util
from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, cast
from uuid import uuid4

import pytest
from sqlalchemy import Column, MetaData, Table, event, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import Session

from onyx.db.engine.sql_engine import SqlEngine
from onyx.db.models import UserUsage
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR


def adapter() -> Any:
    name = "onyx.db.orgmesh_usage_snapshot"
    assert importlib.util.find_spec(name) is not None, (
        "read-only source adapter is missing"
    )
    return importlib.import_module(name)


@pytest.fixture
def source(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[tuple[Engine, str, datetime], None, None]:
    adapter()  # Report missing code before external prerequisites.
    SqlEngine.init_engine(
        pool_size=1, max_overflow=0, connect_args={"connect_timeout": 2}
    )
    engine = SqlEngine.get_engine()
    schema = "orgmesh_snapshot_test_" + uuid4().hex
    metadata = MetaData(schema=schema)
    Table("user", metadata, Column("id", UUID(as_uuid=True), primary_key=True))
    cast(Table, UserUsage.__table__).to_metadata(metadata, schema=schema)
    with engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        metadata.create_all(connection)
    token = CURRENT_TENANT_ID_CONTEXTVAR.set(schema)
    monkeypatch.setenv("ORGMESH_ENTERPRISE_USAGE_ENABLED", "true")
    monkeypatch.setenv("ORGMESH_ENTERPRISE_TENANT_ID", schema)
    day = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    try:
        yield engine, schema, day
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(token)
        with engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))


def seed(
    engine: Engine, schema: str, day: datetime, *, cost: str = "123456789012.123456"
) -> int:
    with engine.begin() as connection:
        return connection.execute(
            text(f'''INSERT INTO "{schema}".user_usage
            (actor_kind, system_attribution, window_start, model, flow, provider, incognito,
             input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens, cost_cents)
            VALUES ('USER', NULL, :day, 'model', 'chat', '', true, 9007199254740993, 5, 4, 2, :cost)
            RETURNING id'''),
            {"day": day, "cost": Decimal(cost)},
        ).scalar_one()


def read(schema: str, day: datetime):
    return adapter().read_usage_snapshot(
        tenant_id=schema, start=day, end=day + timedelta(days=1)
    )


def inspect_source_settings(
    connection: Connection,
    _stream_cursor: object,
    statement: str,
    settings: list[tuple[str, str]],
) -> None:
    if "user_usage" not in statement or not statement.lstrip().startswith("SELECT"):
        return
    dbapi_connection = connection.connection.dbapi_connection
    assert dbapi_connection is not None
    probe = dbapi_connection.cursor()
    try:
        probe.execute("SHOW transaction_read_only")
        readonly_row = probe.fetchone()
        assert readonly_row is not None
        readonly = readonly_row[0]
        probe.execute("SHOW transaction_isolation")
        isolation_row = probe.fetchone()
        assert isolation_row is not None
        settings.append((readonly, isolation_row[0]))
    finally:
        probe.close()


def test_source_read_only(
    source: tuple[Engine, str, datetime],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, schema, day = source
    row_id = seed(engine, schema, day)
    settings: list[tuple[str, str]] = []
    source_adapter = adapter()
    real_get_session = source_adapter.get_session_with_tenant

    def inspect_view(
        connection, cursor, statement, _parameters, _context, _executemany
    ):
        inspect_source_settings(connection, cursor, statement, settings)

    @contextmanager
    def observed_session(**kwargs: Any) -> Generator[Session, None, None]:
        with real_get_session(**kwargs) as session:
            connection = session.bind
            assert isinstance(connection, Connection)
            event.listen(connection, "before_cursor_execute", inspect_view)
            try:
                yield session
            finally:
                event.remove(connection, "before_cursor_execute", inspect_view)

    monkeypatch.setattr(source_adapter, "get_session_with_tenant", observed_session)
    snapshot = read(schema, day)
    assert settings == [("on", "repeatable read")]
    assert snapshot.rows[0].source_row_id == row_id
    with engine.connect() as connection:
        assert (
            connection.execute(
                text(f'SELECT count(*) FROM "{schema}".user_usage')
            ).scalar_one()
            == 1
        )


def test_snapshot_decimal_exact(source: tuple[Engine, str, datetime]) -> None:
    engine, schema, day = source
    seed(engine, schema, day)
    row = read(schema, day).rows[0]
    assert row.cost_cents == "123456789012.123456"
    assert row.input_tokens == 9007199254740993
    assert (row.incognito, row.actor_kind, row.user_id) == (True, "USER", None)


def test_upsert_without_updated_at_is_detected(
    source: tuple[Engine, str, datetime],
) -> None:
    engine, schema, day = source
    row_id = seed(engine, schema, day, cost="0.000001")
    first = read(schema, day).rows[0]
    with engine.begin() as connection:
        before = connection.execute(
            text(f'SELECT updated_at FROM "{schema}".user_usage WHERE id=:id'),
            {"id": row_id},
        ).scalar_one()
        connection.execute(
            text(
                f'UPDATE "{schema}".user_usage SET input_tokens=input_tokens+7, cost_cents=0.000002 WHERE id=:id'
            ),
            {"id": row_id},
        )
        after = connection.execute(
            text(f'SELECT updated_at FROM "{schema}".user_usage WHERE id=:id'),
            {"id": row_id},
        ).scalar_one()
    second = read(schema, day).rows[0]
    assert before == after
    assert first.source_row_id == second.source_row_id == row_id
    assert second.input_tokens == first.input_tokens + 7
    assert second.cost_cents == "0.000002"


def test_reset_and_null_user(source: tuple[Engine, str, datetime]) -> None:
    engine, schema, day = source
    user_id = uuid4()
    row_id = seed(engine, schema, day)
    with engine.begin() as connection:
        connection.execute(
            text(f'INSERT INTO "{schema}"."user" (id) VALUES (:id)'), {"id": user_id}
        )
        connection.execute(
            text(f'UPDATE "{schema}".user_usage SET user_id=:uid WHERE id=:id'),
            {"uid": user_id, "id": row_id},
        )
    assert read(schema, day).rows[0].user_id == str(user_id)
    with engine.begin() as connection:
        connection.execute(
            text(f'DELETE FROM "{schema}"."user" WHERE id=:id'), {"id": user_id}
        )
    row = read(schema, day).rows[0]
    assert (
        row.source_row_id == row_id and row.user_id is None and row.actor_kind == "USER"
    )
    with engine.begin() as connection:
        connection.execute(text(f'DELETE FROM "{schema}".user_usage'))
    assert read(schema, day).rows == ()
    new_id = seed(engine, schema, day)
    assert read(schema, day).rows[0].source_row_id == new_id


def test_two_configured_instances_are_schema_isolated(
    source: tuple[Engine, str, datetime], monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, schema, day = source
    seed(engine, schema, day)
    other = "orgmesh_snapshot_test_" + uuid4().hex
    metadata = MetaData(schema=other)
    Table("user", metadata, Column("id", UUID(as_uuid=True), primary_key=True))
    cast(Table, UserUsage.__table__).to_metadata(metadata, schema=other)
    with engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{other}"'))
        metadata.create_all(connection)
    token = CURRENT_TENANT_ID_CONTEXTVAR.set(other)
    monkeypatch.setenv("ORGMESH_ENTERPRISE_TENANT_ID", other)
    try:
        assert read(other, day).rows == ()
        with pytest.raises(ValueError):
            read(schema, day)
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(token)
        with engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{other}" CASCADE'))
