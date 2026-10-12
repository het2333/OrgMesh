"""The producer publishes complete, leased source views without retries."""

import importlib
import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import httpx
import pytest

from onyx.error_handling.exceptions import OnyxError
from onyx.orgmesh_enterprise.client import EnterpriseClient
from onyx.orgmesh_enterprise.config import EnterpriseConfig
from onyx.orgmesh_enterprise.models import (
    Coverage,
    EnterpriseOperation,
    PublishedSnapshot,
    SnapshotBatch,
    SnapshotLease,
    SnapshotManifest,
    StageAck,
    UsageBeginRequest,
)

FIXTURES = Path(__file__).resolve().parents[4] / "contracts/orgmesh-enterprise/fixtures"


def snapshot_module() -> Any:
    name = "onyx.orgmesh_enterprise.snapshot"
    assert importlib.util.find_spec(name) is not None, "usage producer is missing"
    return importlib.import_module(name)


def task_module() -> Any:
    name = "onyx.background.celery.tasks.orgmesh_enterprise_tasks"
    assert importlib.util.find_spec(name) is not None, "usage task is missing"
    return importlib.import_module(name)


def ready_coverage() -> Coverage:
    coverage = ready_lease().coverage
    assert coverage is not None
    return coverage


def fixture() -> dict[str, Any]:
    return json.loads((FIXTURES / "usage-digest.json").read_text())


def ready_lease() -> SnapshotLease:
    today = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return SnapshotLease(
        status="ready",
        revision=7,
        activated_at=today - timedelta(hours=12),
        collection_start=today,
        coverage=Coverage.model_validate(
            {"from": today, "to": today + timedelta(days=1)}
        ),
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=45),
    )


def test_producer_uses_shared_exact_digest_bytes() -> None:
    module = snapshot_module()
    data = fixture()
    batch = SnapshotBatch.model_validate_json(json.dumps(data["batch"]))
    lease = SnapshotLease.model_validate_json(json.dumps(data["lease"]))
    manifest = SnapshotManifest.model_validate_json(json.dumps(data["manifest"]))
    assert (
        module.batch_preimage(batch.index, batch.rows).hex()
        == data["batch_preimage_hex"]
    )
    assert module.batch_digest(batch.index, batch.rows) == batch.digest
    assert module.canonical_batch_bytes(batch) == 742
    assert (
        module.manifest_preimage(lease, manifest.batches).hex()
        == data["manifest_preimage_hex"]
    )
    assert module.make_manifest(lease, manifest.batches) == manifest


def test_client_adds_only_bounded_producer_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert hasattr(EnterpriseClient, "begin"), "producer begin is missing"
    assert hasattr(EnterpriseClient, "stage"), "producer stage is missing"
    assert hasattr(EnterpriseClient, "commit"), "producer commit is missing"
    data = fixture()
    sent: list[dict[str, Any]] = []

    def upstream(request: httpx.Request) -> httpx.Response:
        envelope = json.loads(request.content)
        sent.append(envelope)
        operation = envelope["request"]["operation"]
        key = {
            "usage.begin": "lease",
            "usage.stage": "ack",
            "usage.commit": "published",
        }[operation]
        published = dict(data["manifest"])
        published = {k: published[k] for k in ("digest", "total_rows", "total_bytes")}
        published.update(
            revision=7,
            coverage=data["lease"]["coverage"],
            published_at="2026-10-13T12:00:00Z",
        )
        return httpx.Response(
            200,
            json={
                "operation": operation,
                key: published if key == "published" else data[key],
            },
        )

    monkeypatch.setenv("MULTI_TENANT", "false")
    client = EnterpriseClient(
        EnterpriseConfig(usage_enabled=True), transport=httpx.MockTransport(upstream)
    )
    coverage = Coverage.model_validate_json(json.dumps(data["lease"]["coverage"]))
    lease = client.begin(coverage)
    ack = client.stage(
        lease, SnapshotBatch.model_validate_json(json.dumps(data["batch"]))
    )
    result = client.commit(
        lease, SnapshotManifest.model_validate_json(json.dumps(data["manifest"]))
    )
    assert (ack.byte_count, result.revision) == (742, 7)
    assert [s["identity"]["operation"] for s in sent] == [
        "usage.begin",
        "usage.stage",
        "usage.commit",
    ]
    assert all(
        s["identity"]["actor_kind"] == "producer" and s["identity"]["user_id"] == ""
        for s in sent
    )
    assert len({s["identity"]["request_id"] for s in sent}) == 3
    for entry in sent:
        identity = entry["identity"]
        issued = datetime.fromisoformat(identity["issued_at"])
        expiry = datetime.fromisoformat(identity["expires_at"])
        assert expiry - issued == timedelta(seconds=5)
    from onyx.orgmesh_enterprise.models import TrustedIdentity

    identity = TrustedIdentity.model_validate_json(json.dumps(sent[0]["identity"]))
    with pytest.raises(OnyxError) as error:
        client.call(
            EnterpriseOperation.USAGE_BEGIN,
            identity,
            UsageBeginRequest(coverage=coverage),
        )
    assert error.value.status_code == 403
    with pytest.raises(OnyxError):
        EnterpriseClient(
            EnterpriseConfig(), transport=httpx.MockTransport(upstream)
        ).begin(coverage)


def publication_receipt(
    lease: SnapshotLease, manifest: SnapshotManifest, **_kwargs: Any
) -> PublishedSnapshot:
    assert lease.coverage is not None
    return PublishedSnapshot(
        revision=lease.revision,
        digest=manifest.digest,
        coverage=lease.coverage,
        published_at=datetime.now(timezone.utc),
        total_rows=manifest.total_rows,
        total_bytes=manifest.total_bytes,
    )


def setup_run(monkeypatch: pytest.MonkeyPatch, *, waiting: bool = False):
    module = snapshot_module()
    lease = ready_lease()
    if waiting:
        lease = lease.model_copy(
            update={
                "status": "waiting",
                "revision": 0,
                "coverage": None,
                "expires_at": None,
            }
        )
    client = Mock()
    client.begin.return_value = lease
    client.commit.side_effect = publication_receipt
    source = Mock(
        return_value=module.UsageSnapshot(
            coverage=lease.coverage or ready_lease().coverage, rows=()
        )
    )
    monkeypatch.setattr(module, "read_usage_snapshot", source)
    monkeypatch.setattr(module, "EnterpriseClient", lambda _: client)
    return module, lease, client, source


def test_waiting_begin_never_reads_source(monkeypatch: pytest.MonkeyPatch) -> None:
    module, _, client, source = setup_run(monkeypatch, waiting=True)
    module.publish_usage_snapshot(
        tenant_id="public", config=EnterpriseConfig(usage_enabled=True)
    )
    assert not source.called and not client.stage.called and not client.commit.called


def test_ready_lease_precedes_fresh_read_and_empty_reset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module, lease, client, source = setup_run(monkeypatch)
    events: list[str] = []
    client.begin.side_effect = lambda _, **_kwargs: events.append("begin") or lease
    original = source.return_value
    source.side_effect = lambda **_: events.append("source") or original
    client.commit.side_effect = lambda *args, **kwargs: (
        events.append("commit") or publication_receipt(*args, **kwargs)
    )
    module.publish_usage_snapshot(
        tenant_id="public", config=EnterpriseConfig(usage_enabled=True)
    )
    assert events == ["begin", "source", "commit"]
    assert source.call_args.kwargs["start"] == lease.coverage.from_
    assert source.call_args.kwargs["end"] == lease.coverage.to
    assert source.call_args.kwargs["tenant_id"] == "public"
    requested = client.begin.call_args.args[0]
    today = lease.coverage.from_
    assert requested == Coverage.model_validate(
        {"from": today - timedelta(days=89), "to": today + timedelta(days=1)}
    )
    manifest = client.commit.call_args.args[1]
    assert (
        manifest.complete
        and manifest.batches == ()
        and manifest.total_rows == manifest.total_bytes == 0
    )


@pytest.mark.parametrize("failure", ["source", "stage", "oversized", "bad_ack"])
def test_failure_abandons_revision_without_subset_commit(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    module, lease, client, source = setup_run(monkeypatch)
    row = SnapshotBatch.model_validate_json(json.dumps(fixture()["batch"])).rows[0]
    row = row.model_copy(update={"window_start": lease.coverage.from_})
    source.return_value = module.UsageSnapshot(coverage=lease.coverage, rows=(row,))
    if failure == "source":
        source.side_effect = RuntimeError("read failed")
    elif failure == "oversized":
        from onyx.error_handling.error_codes import OnyxErrorCode

        client.stage.side_effect = OnyxError(OnyxErrorCode.PAYLOAD_TOO_LARGE)
    elif failure == "stage":
        client.stage.side_effect = RuntimeError("stage failed")
    else:
        client.stage.return_value = StageAck(
            index=0, digest="0" * 64, row_count=1, byte_count=1
        )
    with pytest.raises((RuntimeError, ValueError, OnyxError)):
        module.publish_usage_snapshot(
            tenant_id="public", config=EnterpriseConfig(usage_enabled=True)
        )
    assert not client.commit.called
    assert client.begin.call_count == 1
    assert client.stage.call_count <= 1


def test_chunking_leaves_transport_headroom_and_uses_ack_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module, lease, client, source = setup_run(monkeypatch)
    row = SnapshotBatch.model_validate_json(json.dumps(fixture()["batch"])).rows[0]
    rows = tuple(
        row.model_copy(
            update={
                "source_row_id": n + 1,
                "window_start": lease.coverage.from_,
                "model": "😀" * 512,
            }
        )
        for n in range(1001)
    )
    source.return_value = module.UsageSnapshot(coverage=lease.coverage, rows=rows)

    def stage(_lease, batch, **_kwargs):
        assert len(batch.rows) <= 1000
        assert module.canonical_batch_bytes(batch) <= module.BATCH_TARGET_BYTES
        return StageAck(
            index=batch.index,
            digest=batch.digest,
            row_count=len(batch.rows),
            byte_count=module.canonical_batch_bytes(batch),
        )

    client.stage.side_effect = stage
    module.publish_usage_snapshot(
        tenant_id="public", config=EnterpriseConfig(usage_enabled=True)
    )
    manifest = client.commit.call_args.args[1]
    assert manifest.total_rows == 1001
    assert manifest.total_bytes == sum(a.byte_count for a in manifest.batches)
    assert len(manifest.batches) > 1


def test_deadline_expiry_prevents_read_and_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module, lease, client, source = setup_run(monkeypatch)
    clock = [0.0]
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])
    client.begin.side_effect = lambda _, **_kwargs: clock.__setitem__(0, 45.0) or lease
    with pytest.raises(TimeoutError):
        module.publish_usage_snapshot(
            tenant_id="public", config=EnterpriseConfig(usage_enabled=True)
        )
    assert not source.called and not client.commit.called
    clock[0] = 0
    client.begin.side_effect = None
    source.side_effect = lambda **_: clock.__setitem__(0, 44.0) or source.return_value
    with pytest.raises(TimeoutError):
        module.publish_usage_snapshot(
            tenant_id="public", config=EnterpriseConfig(usage_enabled=True)
        )
    assert not client.commit.called


@pytest.mark.parametrize("tenant", ["", "other"])
def test_missing_tenant_is_rejected(
    monkeypatch: pytest.MonkeyPatch, tenant: str
) -> None:
    module, _, client, source = setup_run(monkeypatch)
    with pytest.raises(ValueError):
        module.publish_usage_snapshot(
            tenant_id=tenant, config=EnterpriseConfig(usage_enabled=True)
        )
    assert not source.called and not client.begin.called


def test_disabled_collection_never_reads(monkeypatch: pytest.MonkeyPatch) -> None:
    module, _, client, source = setup_run(monkeypatch)
    module.publish_usage_snapshot(tenant_id="public", config=EnterpriseConfig())
    assert not source.called and not client.begin.called


def test_explicit_expiration(monkeypatch: pytest.MonkeyPatch) -> None:
    task = task_module()
    from onyx.background.celery.tasks.beat_schedule import get_tasks_to_schedule
    from onyx.configs.constants import OnyxCeleryQueues, OnyxCeleryTask

    entries = [
        entry
        for entry in get_tasks_to_schedule()
        if entry["task"] == OnyxCeleryTask.PRODUCE_ORGMESH_USAGE_SNAPSHOT
    ]
    assert len(entries) == 1
    entry = entries[0]
    assert entry["schedule"] == timedelta(seconds=60)
    assert entry["options"]["expires"] == 55
    assert entry["options"]["queue"] == OnyxCeleryQueues.PRIMARY
    assert entry["kwargs"] == {"tenant_id": "public"}
    assert (
        task.produce_usage_snapshot.name
        == OnyxCeleryTask.PRODUCE_ORGMESH_USAGE_SNAPSHOT
    )
    producer = Mock()
    monkeypatch.setattr(task, "publish_usage_snapshot", producer)
    monkeypatch.setattr(
        task.EnterpriseConfig, "from_env", lambda: EnterpriseConfig(usage_enabled=True)
    )
    task.produce_usage_snapshot.run(tenant_id="public")
    assert producer.call_args.kwargs["tenant_id"] == "public"
    producer.side_effect = RuntimeError("bounded failed revision")
    task.produce_usage_snapshot.run(tenant_id="public")
    assert producer.call_count == 2


def test_bff_query_interface_is_typed() -> None:
    import inspect

    from onyx.server.features.orgmesh_enterprise import api

    assert "query" in inspect.signature(api.get_usage_summary).parameters


def test_snapshot_connection_is_opt_in_and_preserves_source_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sqlalchemy import create_engine

    from onyx.db.engine import sql_engine
    from onyx.db.engine.sql_engine import EngineProfile

    name = "onyx.db.engine.orgmesh_snapshot"
    assert importlib.util.find_spec(name) is not None, (
        "bounded source connection helper is missing"
    )
    bounded = importlib.import_module(name)
    original = create_engine("postgresql+psycopg2://source:test@localhost/source_db")
    profile = EngineProfile(
        use_iam=False,
        engine_kwargs={
            "pool_size": 10,
            "max_overflow": 5,
            "pool_pre_ping": True,
            "pool_recycle": 100,
            "connect_args": {
                "sslmode": "verify-full",
                "sslrootcert": "/reviewed/ca.pem",
                "keepalives": 1,
                "options": "-c application_name=onyx",
            },
        },
    )
    monkeypatch.setattr(sql_engine.SqlEngine, "get_engine_profile", lambda: profile)
    monkeypatch.setattr(sql_engine, "get_engine_for_tenant", lambda _: original)
    options: list[dict[str, Any]] = []
    real_create = bounded.create_engine

    def create(url, **kwargs):
        assert url == original.url
        options.append(kwargs)
        return real_create(url, **kwargs)

    monkeypatch.setattr(bounded, "create_engine", create)
    with sql_engine.get_session_with_tenant(tenant_id="public") as session:
        assert session.bind is original
    assert options == []
    clone = bounded.bounded_snapshot_engine(
        original, deadline=bounded.time.monotonic() + 45
    )
    assert clone is not original
    from sqlalchemy.pool import NullPool

    assert isinstance(clone.pool, NullPool)
    assert options[0]["pool_pre_ping"] is False
    assert all(
        key not in options[0]
        for key in ("pool_size", "max_overflow", "pool_timeout", "pool_recycle")
    )
    args = options[0]["connect_args"]
    assert args["connect_timeout"] == 2
    assert (
        args["sslmode"] == "verify-full"
        and args["sslrootcert"] == "/reviewed/ca.pem"
        and args["keepalives"] == 1
    )
    assert "application_name=onyx" in args["options"]
    assert (
        "statement_timeout=" in args["options"]
        and "lock_timeout=" in args["options"]
        and "idle_in_transaction_session_timeout=" in args["options"]
    )
    assert profile.engine_kwargs["pool_pre_ping"] is True
    assert "connect_timeout" not in profile.engine_kwargs["connect_args"]
    clone.dispose()
    original.dispose()


@pytest.mark.parametrize(
    "case",
    [
        "iam",
        "creator",
        "hosts",
        "driver",
        "hook",
        "expired",
        "hostaddrs",
        "service",
        "factory",
        "env_hosts",
        "env_service",
    ],
)
def test_unsupported_snapshot_connections_fail_before_connect(
    monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    from sqlalchemy import create_engine, event

    from onyx.db.engine import sql_engine
    from onyx.db.engine.sql_engine import EngineProfile

    name = "onyx.db.engine.orgmesh_snapshot"
    assert importlib.util.find_spec(name) is not None, (
        "bounded source connection helper is missing"
    )
    bounded = importlib.import_module(name)
    url = (
        "sqlite://"
        if case == "driver"
        else "postgresql+psycopg2://source:test@localhost/source_db"
    )
    engine = create_engine(url)
    kwargs: dict[str, Any] = {}
    if case == "creator":
        kwargs["creator"] = lambda: pytest.fail("must not connect")
    if case == "hosts":
        kwargs["connect_args"] = {"host": "one,two"}
    if case == "hostaddrs":
        engine.dispose()
        engine = create_engine(
            "postgresql+psycopg2://source:test@/source_db?hostaddr=127.0.0.1&hostaddr=127.0.0.2"
        )
    if case == "service":
        kwargs["connect_args"] = {"service": "opaque"}
    if case == "factory":
        kwargs["connect_args"] = {
            "connection_factory": lambda: pytest.fail("must not connect")
        }
    if case == "env_hosts":
        engine.dispose()
        engine = create_engine("postgresql+psycopg2://source:test@/source_db")
        monkeypatch.setenv("PGHOST", "one,two")
    if case == "env_service":
        monkeypatch.setenv("PGSERVICE", "opaque")
    if case == "hook":
        event.listen(engine, "do_connect", lambda *_: pytest.fail("must not connect"))
    monkeypatch.setattr(
        sql_engine.SqlEngine,
        "get_engine_profile",
        lambda: EngineProfile(use_iam=case == "iam", engine_kwargs=kwargs),
    )
    monkeypatch.setattr(
        bounded,
        "create_engine",
        lambda *_args, **_kwargs: pytest.fail(
            "unsupported configuration must not construct source engine"
        ),
    )
    with pytest.raises((ValueError, TimeoutError)):
        bounded.bounded_snapshot_engine(
            engine,
            deadline=bounded.time.monotonic() + (-1 if case == "expired" else 45),
        )
    engine.dispose()


def test_source_select_is_decimal_and_read_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    name = "onyx.db.orgmesh_usage_snapshot"
    assert importlib.util.find_spec(name) is not None, (
        "read-only source adapter is missing"
    )
    adapter = importlib.import_module(name)
    from contextlib import contextmanager
    from decimal import Decimal

    from sqlalchemy.dialects import postgresql

    from onyx.db.enums import UsageActorKind

    day = ready_coverage().from_
    values = {
        "id": 42,
        "actor_kind": UsageActorKind.USER,
        "user_id": None,
        "system_attribution": None,
        "window_start": day,
        "model": "model",
        "flow": "chat",
        "provider": "",
        "incognito": True,
        "input_tokens": 9007199254740993,
        "output_tokens": 5,
        "cache_read_tokens": 4,
        "cache_creation_tokens": 2,
        "cost_cents": Decimal("123456789012.123456"),
    }
    session = Mock()
    session.execute.return_value.mappings.return_value = [values]

    @contextmanager
    def get_session(**kwargs):
        assert kwargs["tenant_id"] == "public" and kwargs["snapshot_deadline"] > 0
        yield session

    monkeypatch.setattr(adapter, "get_session_with_tenant", get_session)
    monkeypatch.setenv("ORGMESH_ENTERPRISE_USAGE_ENABLED", "true")
    result = adapter.read_usage_snapshot(
        tenant_id="public", start=day, end=day + timedelta(days=1)
    )
    assert result.rows[0].cost_cents == "123456789012.123456"
    assert result.rows[0].source_row_id == 42 and result.rows[0].user_id is None
    assert result.rows[0].input_tokens == 9007199254740993
    assert session.connection.call_args.kwargs["execution_options"] == {
        "isolation_level": "REPEATABLE READ",
        "postgresql_readonly": True,
    }
    select = session.execute.call_args.args[0]
    sql = str(select.compile(dialect=postgresql.dialect()))
    assert "CAST(user_usage.cost_cents AS NUMERIC(18, 6))" in sql
    assert "user_usage.window_start >=" in sql and "user_usage.window_start <" in sql
    assert "ORDER BY user_usage.id" in sql and "LIMIT" in sql
    assert "updated_at" not in sql and "GROUP BY" not in sql
    assert (
        session.commit.call_count == 0
        and session.add.call_count == 0
        and session.flush.call_count == 0
    )
    values["cost_cents"] = 0.1
    with pytest.raises(ValueError):
        adapter.read_usage_snapshot(
            tenant_id="public", start=day, end=day + timedelta(days=1)
        )


def test_expired_receiver_lease_prevents_source_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module, lease, client, source = setup_run(monkeypatch)
    client.begin.return_value = lease.model_copy(
        update={"expires_at": datetime.now(timezone.utc) - timedelta(seconds=1)}
    )
    with pytest.raises(TimeoutError):
        module.publish_usage_snapshot(
            tenant_id="public", config=EnterpriseConfig(usage_enabled=True)
        )
    assert not source.called and not client.commit.called


def test_later_stage_failure_never_publishes_successful_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module, lease, client, source = setup_run(monkeypatch)
    row = SnapshotBatch.model_validate_json(json.dumps(fixture()["batch"])).rows[0]
    source.return_value = module.UsageSnapshot(
        coverage=lease.coverage,
        rows=tuple(
            row.model_copy(
                update={"source_row_id": n + 1, "window_start": lease.coverage.from_}
            )
            for n in range(1001)
        ),
    )

    def stage(_lease, batch, **_kwargs):
        if batch.index == 1:
            raise RuntimeError("second batch failed")
        return StageAck(
            index=0,
            digest=batch.digest,
            row_count=len(batch.rows),
            byte_count=module.canonical_batch_bytes(batch),
        )

    client.stage.side_effect = stage
    with pytest.raises(RuntimeError, match="second batch failed"):
        module.publish_usage_snapshot(
            tenant_id="public", config=EnterpriseConfig(usage_enabled=True)
        )
    assert client.stage.call_count == 2 and not client.commit.called


def test_oversized_transport_rejection_happens_before_receiver_dispatch() -> None:
    from onyx.orgmesh_enterprise.models import SnapshotRow

    lease = ready_lease()
    assert lease.coverage is not None
    row = SnapshotRow.model_validate_json(json.dumps(fixture()["batch"]["rows"][0]))
    rows = tuple(
        row.model_copy(
            update={
                "source_row_id": n + 1,
                "window_start": lease.coverage.from_,
                "model": "😀" * 512,
                "flow": "😀" * 512,
                "provider": "😀" * 512,
            }
        )
        for n in range(1000)
    )
    requests: list[httpx.Request] = []
    client = EnterpriseClient(
        EnterpriseConfig(usage_enabled=True),
        transport=httpx.MockTransport(
            lambda request: requests.append(request) or httpx.Response(200)
        ),
    )
    with pytest.raises(OnyxError) as error:
        client.stage(lease, SnapshotBatch(index=0, rows=rows, digest="0" * 64))
    assert error.value.status_code == 413 and requests == []


@pytest.mark.parametrize(
    "cost", ["-0.000001", "0.0000001", "1000000000000.000000", "NaN", "Infinity"]
)
def test_decimal_source_range_is_enforced(cost: str) -> None:
    from decimal import Decimal

    from onyx.db.orgmesh_usage_snapshot import _exact_cost

    with pytest.raises(ValueError):
        _exact_cost(Decimal(cost))


def test_bff_uses_actual_admin_and_pat_gate_and_has_no_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi.routing import APIRoute
    from starlette.requests import Request

    from onyx.db.enums import Permission
    from onyx.server.features.orgmesh_enterprise import api
    from tests.unit.orgmesh.test_enterprise_identity import admin

    route = next(
        route
        for route in api.router.routes
        if isinstance(route, APIRoute) and route.path.endswith("/usage/summary")
    )
    assert [dependency.call for dependency in route.dependant.dependencies] == [
        api.admin_user
    ]
    assert route.dependant.dependencies[0].call is not None
    assert route.dependant.dependencies[0].call is not None
    request = Request({"type": "http", "headers": []})
    request.state.token_scopes = [Permission.READ_SEARCH]
    with pytest.raises(OnyxError) as restricted:
        route.dependant.dependencies[0].call(request=request, user=admin()).send(None)
    assert restricted.value.status_code == 403
    day = ready_coverage().from_
    from onyx.orgmesh_enterprise.models import UsageQuery

    query = UsageQuery(start=day, end=day + timedelta(days=1))
    client = EnterpriseClient(
        EnterpriseConfig(usage_enabled=True),
        transport=httpx.MockTransport(lambda _: httpx.Response(503)),
    )
    monkeypatch.setattr(api, "get_config", lambda: EnterpriseConfig(usage_enabled=True))
    monkeypatch.setattr(api, "get_client", lambda: client)
    with pytest.raises(OnyxError) as unavailable:
        api.get_usage_summary(query, admin())
    assert unavailable.value.status_code == 503
    monkeypatch.setattr(api, "get_config", lambda: EnterpriseConfig())
    with pytest.raises(OnyxError) as disabled:
        api.get_usage_summary(query, admin())
    assert disabled.value.status_code == 503
    assert api.get_capabilities().usage_enabled is False


def test_source_rejects_disabled_or_missing_tenant_before_any_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from onyx.db import orgmesh_usage_snapshot as source

    day = ready_coverage().from_
    monkeypatch.setattr(
        source,
        "get_session_with_tenant",
        lambda **_: pytest.fail("must not access source"),
    )
    monkeypatch.setenv("ORGMESH_ENTERPRISE_USAGE_ENABLED", "false")
    with pytest.raises(ValueError):
        source.read_usage_snapshot(
            tenant_id="public", start=day, end=day + timedelta(days=1)
        )
    monkeypatch.setenv("ORGMESH_ENTERPRISE_USAGE_ENABLED", "true")
    with pytest.raises(ValueError):
        source.read_usage_snapshot(tenant_id="", start=day, end=day + timedelta(days=1))
    with pytest.raises(ValueError):
        source.read_usage_snapshot(
            tenant_id="other", start=day, end=day + timedelta(days=1)
        )


def test_producer_transport_matches_shared_fixture_end_to_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = snapshot_module()
    data = fixture()
    lease = SnapshotLease.model_validate_json(json.dumps(data["lease"]))
    batch = SnapshotBatch.model_validate_json(json.dumps(data["batch"]))

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 10, 13, 12, tzinfo=timezone.utc).astimezone(tz)

    monkeypatch.setattr(module, "datetime", FrozenDateTime)
    events: list[str] = []

    def source(**kwargs):
        assert events == ["usage.begin"]
        assert kwargs["start"] == datetime(2026, 10, 13, tzinfo=timezone.utc)
        assert kwargs["end"] == datetime(2026, 10, 14, tzinfo=timezone.utc)
        events.append("source")
        return module.UsageSnapshot(coverage=lease.coverage, rows=batch.rows)

    def upstream(request: httpx.Request):
        envelope = json.loads(request.content)
        payload = envelope["request"]
        assert envelope["identity"]["actor_kind"] == "producer"
        operation = payload["operation"]
        events.append(operation)
        if operation == "usage.begin":
            return httpx.Response(
                200, json={"operation": operation, "lease": data["lease"]}
            )
        if operation == "usage.stage":
            assert payload["batch"] == data["batch"]
            return httpx.Response(
                200, json={"operation": operation, "ack": data["ack"]}
            )
        assert payload["manifest"] == data["manifest"]
        return httpx.Response(
            200,
            json={
                "operation": operation,
                "published": {
                    "revision": 7,
                    "digest": data["manifest"]["digest"],
                    "coverage": data["lease"]["coverage"],
                    "published_at": "2026-10-13T12:00:00Z",
                    "total_rows": 2,
                    "total_bytes": 742,
                },
            },
        )

    config = EnterpriseConfig(usage_enabled=True)
    client = EnterpriseClient(config, transport=httpx.MockTransport(upstream))
    monkeypatch.setattr(module, "EnterpriseClient", lambda _: client)
    monkeypatch.setattr(module, "read_usage_snapshot", source)
    module.publish_usage_snapshot(tenant_id="public", config=config)
    assert events == ["usage.begin", "source", "usage.stage", "usage.commit"]


def test_producer_transport_abandons_drip_response_at_total_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import inspect
    import time

    assert "deadline" in inspect.signature(EnterpriseClient.begin).parameters, (
        "producer transport must accept its operation deadline"
    )
    clock = [44.0]
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    chunks: list[int] = []
    data = fixture()
    response = json.dumps({"operation": "usage.begin", "lease": data["lease"]}).encode()

    class DripStream(httpx.SyncByteStream):
        def __iter__(self):
            for index, instant in enumerate((44.5, 45.1, 45.5)):
                clock[0] = instant
                chunks.append(index)
                yield response[index : index + 1]

    client = EnterpriseClient(
        EnterpriseConfig(usage_enabled=True),
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, stream=DripStream())
        ),
    )
    coverage = Coverage.model_validate_json(json.dumps(data["lease"]["coverage"]))
    with pytest.raises(OnyxError) as error:
        client.begin(coverage, deadline=45.0)
    assert error.value.status_code == 503
    assert chunks == [0, 1]


def test_trickle_stage_deadline_never_commits_a_revision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import time

    module = snapshot_module()
    lease = ready_lease()
    assert lease.coverage is not None
    row = (
        SnapshotBatch.model_validate_json(json.dumps(fixture()["batch"]))
        .rows[0]
        .model_copy(update={"window_start": lease.coverage.from_})
    )
    clock = [0.0]
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    operations: list[str] = []
    chunks: list[int] = []

    class DripStream(httpx.SyncByteStream):
        def __iter__(self):
            for index in range(3):
                clock[0] = 45.1 + index
                chunks.append(index)
                yield b"{"

    def upstream(request: httpx.Request):
        operation = json.loads(request.content)["request"]["operation"]
        operations.append(operation)
        if operation == "usage.begin":
            return httpx.Response(
                200,
                json={"operation": operation, "lease": lease.model_dump(mode="json")},
            )
        assert operation == "usage.stage"
        return httpx.Response(200, stream=DripStream())

    config = EnterpriseConfig(usage_enabled=True)
    client = EnterpriseClient(config, transport=httpx.MockTransport(upstream))
    monkeypatch.setattr(module, "EnterpriseClient", lambda _: client)
    monkeypatch.setattr(
        module,
        "read_usage_snapshot",
        lambda **_: module.UsageSnapshot(coverage=lease.coverage, rows=(row,)),
    )
    with pytest.raises(OnyxError):
        module.publish_usage_snapshot(tenant_id="public", config=config)
    assert operations == ["usage.begin", "usage.stage"]
    assert chunks == [0]


def test_mismatched_publication_receipt_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from onyx.orgmesh_enterprise.models import PublishedSnapshot

    module, lease, client, _ = setup_run(monkeypatch)
    assert lease.coverage is not None
    client.commit.side_effect = None
    client.commit.return_value = PublishedSnapshot(
        revision=lease.revision + 1,
        digest="0" * 64,
        coverage=lease.coverage,
        published_at=datetime.now(timezone.utc),
        total_rows=0,
        total_bytes=0,
    )
    with pytest.raises(ValueError, match="publication receipt"):
        module.publish_usage_snapshot(
            tenant_id="public", config=EnterpriseConfig(usage_enabled=True)
        )


@pytest.mark.parametrize(
    "event_name",
    ["connect", "first_connect", "checkout", "engine_connect", "begin", "do_execute"],
)
def test_source_policy_hooks_are_rejected_before_clone(
    monkeypatch: pytest.MonkeyPatch, event_name: str
) -> None:
    from sqlalchemy import create_engine, event

    from onyx.db.engine import orgmesh_snapshot as bounded
    from onyx.db.engine import sql_engine
    from onyx.db.engine.sql_engine import EngineProfile

    engine = create_engine("postgresql+psycopg2://source:test@localhost/source_db")
    event.listen(engine, event_name, lambda *_: None)
    monkeypatch.setattr(
        sql_engine.SqlEngine,
        "get_engine_profile",
        lambda: EngineProfile(use_iam=False, engine_kwargs={}),
    )
    monkeypatch.setattr(
        bounded,
        "create_engine",
        lambda *_args, **_kwargs: pytest.fail(
            "policy hook must be rejected before cloning"
        ),
    )
    try:
        with pytest.raises(ValueError, match="unsupported"):
            bounded.bounded_snapshot_engine(
                engine, deadline=bounded.time.monotonic() + 45
            )
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "key",
    [
        "dsn",
        "service",
        "connection_factory",
        "cursor_factory",
        "async_",
        "async",
        "plugin",
    ],
)
def test_url_driver_overrides_are_rejected_before_clone(
    monkeypatch: pytest.MonkeyPatch, key: str
) -> None:
    from sqlalchemy import create_engine

    from onyx.db.engine import orgmesh_snapshot as bounded
    from onyx.db.engine import sql_engine
    from onyx.db.engine.sql_engine import EngineProfile

    engine = create_engine("postgresql+psycopg2://source:test@localhost/source_db")
    # URL mutation reproduces the resolved-engine entry point without loading a plugin.
    engine.url = engine.url.update_query_dict({key: "host=one,two"})
    monkeypatch.setattr(
        sql_engine.SqlEngine,
        "get_engine_profile",
        lambda: EngineProfile(use_iam=False, engine_kwargs={}),
    )
    monkeypatch.setattr(
        bounded,
        "create_engine",
        lambda *_args, **_kwargs: pytest.fail(
            "opaque URL must be rejected before cloning"
        ),
    )
    try:
        with pytest.raises(ValueError, match="unsupported"):
            bounded.bounded_snapshot_engine(
                engine, deadline=bounded.time.monotonic() + 45
            )
    finally:
        engine.dispose()


@pytest.mark.parametrize("naive", [False, True])
def test_source_timestamp_normalizes_utc_and_rejects_naive(
    monkeypatch: pytest.MonkeyPatch, naive: bool
) -> None:
    from contextlib import contextmanager
    from decimal import Decimal

    from onyx.db import orgmesh_usage_snapshot as source
    from onyx.db.enums import UsageActorKind

    day = ready_coverage().from_
    source_time = (
        day.replace(tzinfo=None)
        if naive
        else day.astimezone(timezone(timedelta(hours=2)))
    )
    values = {
        "id": 42,
        "actor_kind": UsageActorKind.USER,
        "user_id": None,
        "system_attribution": None,
        "window_start": source_time,
        "model": "model",
        "flow": "chat",
        "provider": "",
        "incognito": False,
        "input_tokens": 1,
        "output_tokens": 2,
        "cache_read_tokens": 0,
        "cache_creation_tokens": 0,
        "cost_cents": Decimal("0.123456"),
    }
    session = Mock()
    session.execute.return_value.mappings.return_value = [values]

    @contextmanager
    def get_session(**_kwargs):
        yield session

    monkeypatch.setattr(source, "get_session_with_tenant", get_session)
    monkeypatch.setenv("ORGMESH_ENTERPRISE_USAGE_ENABLED", "true")
    if naive:
        with pytest.raises(ValueError, match="timezone"):
            source.read_usage_snapshot(
                tenant_id="public", start=day, end=day + timedelta(days=1)
            )
    else:
        snapshot = source.read_usage_snapshot(
            tenant_id="public", start=day, end=day + timedelta(days=1)
        )
        assert snapshot.rows[0].window_start == day
        assert snapshot.rows[0].window_start.utcoffset() == timedelta(0)


def test_readonly_probe_uses_separate_cursor_on_source_connection() -> None:
    import importlib.util

    path = (
        Path(__file__).resolve().parents[2]
        / "external_dependency_unit/orgmesh/test_enterprise_snapshot.py"
    )
    spec = importlib.util.spec_from_file_location("isolated_snapshot_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert hasattr(module, "inspect_source_settings"), (
        "source settings probe needs its own ordinary cursor"
    )
    connection = Mock()
    ordinary = connection.connection.dbapi_connection.cursor.return_value
    ordinary.fetchone.side_effect = [("on",), ("repeatable read",)]
    settings: list[tuple[str, str]] = []
    named = Mock()
    named.execute.side_effect = AssertionError(
        "do not execute SHOW on the named source cursor"
    )
    module.inspect_source_settings(
        connection, named, "SELECT id FROM user_usage", settings
    )
    assert settings == [("on", "repeatable read")]
    assert ordinary.execute.call_count == 2 and not named.execute.called
    module.inspect_source_settings(connection, named, "SELECT 1", settings)
    assert connection.connection.dbapi_connection.cursor.call_count == 1


@pytest.mark.parametrize("target", ["engine", "pool"])
def test_class_connect_policy_is_rejected_before_clone(
    monkeypatch: pytest.MonkeyPatch, target: str
) -> None:
    from sqlalchemy import create_engine, event
    from sqlalchemy.engine import Engine
    from sqlalchemy.pool import Pool

    from onyx.db.engine import orgmesh_snapshot as bounded
    from onyx.db.engine import sql_engine
    from onyx.db.engine.sql_engine import EngineProfile

    engine = create_engine("postgresql+psycopg2://source:test@localhost/source_db")
    target_class = Engine if target == "engine" else Pool

    def policy(*_):
        return None

    event.listen(target_class, "connect", policy)
    monkeypatch.setattr(
        sql_engine.SqlEngine,
        "get_engine_profile",
        lambda: EngineProfile(use_iam=False, engine_kwargs={}),
    )
    monkeypatch.setattr(
        bounded,
        "create_engine",
        lambda *_args, **_kwargs: pytest.fail(
            "class policy must be rejected before cloning"
        ),
    )
    try:
        with pytest.raises(ValueError, match="unsupported"):
            bounded.bounded_snapshot_engine(
                engine, deadline=bounded.time.monotonic() + 45
            )
    finally:
        event.remove(target_class, "connect", policy)
        engine.dispose()
