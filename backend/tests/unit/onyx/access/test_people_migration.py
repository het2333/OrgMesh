"""Render migration SQL and exercise its reversible additive tables in SQLite."""

import importlib.util
from io import StringIO
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def migration():
    path = (
        Path(__file__).resolve().parents[4]
        / "alembic/versions/d83f0b6c1e92_add_people_directory.py"
    )
    spec = importlib.util.spec_from_file_location("people_migration", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_people_migration_is_additive_and_follows_orgmesh_head() -> None:
    module = migration()
    assert module.down_revision == "c71e9a2d4f60"
    output = StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output}
    )
    with Operations.context(context):
        module.upgrade()
    sql = output.getvalue()
    assert "CREATE TABLE orgmesh_person" in sql
    assert "CREATE TABLE orgmesh_department" in sql
    assert "FOREIGN KEY(employee_id) REFERENCES orgmesh_person" in sql
    assert "orgmesh_directory_user" not in sql


def test_people_tables_upgrade_and_downgrade_in_disposable_database() -> None:
    module = migration()
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            module.upgrade()
        assert set(sa.inspect(connection).get_table_names()) == {
            "orgmesh_person",
            "orgmesh_department",
            "orgmesh_person_department",
        }
        with Operations.context(context):
            module.downgrade()
        assert sa.inspect(connection).get_table_names() == []
    engine.dispose()
