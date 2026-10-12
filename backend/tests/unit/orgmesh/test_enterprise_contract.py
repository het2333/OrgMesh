"""Contract tests catch unbounded and ambiguous data at the private boundary."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from onyx.orgmesh_enterprise.config import EnterpriseConfig, load_static_branding
from onyx.orgmesh_enterprise.models import (
    AuditQuery,
    BrandingPatch,
    UsageQuery,
    decode_request,
)

FIXTURES = Path(__file__).resolve().parents[4] / "contracts/orgmesh-enterprise/fixtures"


def test_shared_legal_fixture() -> None:
    fixture = json.loads((FIXTURES / "legal.json").read_text())
    request = decode_request(json.dumps(fixture["request"]).encode())
    assert request.operation == "branding.read"


@pytest.mark.parametrize(
    "change",
    [
        {"name": ""},
        {"name": "界" * 51},
        {"greeting": "界" * 121},
        {"expected_version": -1},
        {"expected_version": True},
        {"logo_asset_id": "https://example.com/logo"},
        {"name": "<script>x</script>"},
        {"tenant_id": "other"},
    ],
)
def test_patch_rejects_invalid_fields(change: dict[str, object]) -> None:
    fields: dict[str, object] = {
        "expected_version": 0,
        "name": "OrgMesh",
        "greeting": "",
        "logo_asset_id": "orgmesh-default",
    }
    fields.update(change)
    with pytest.raises(ValidationError):
        BrandingPatch.model_validate(fields)


def test_patch_counts_unicode_characters() -> None:
    patch = BrandingPatch(
        expected_version=0,
        name="界" * 50,
        greeting="界" * 120,
        logo_asset_id="orgmesh-default",
    )
    assert len(patch.name) == 50


@pytest.mark.parametrize(
    "data",
    [
        b'{"operation":"branding.read","role":"admin"}',
        b'{"operation":"branding.read","operation":"audit.list"}',
        b'{"operation":"branding.read"} {}',
        b'{"operation":"branding.read","value":NaN}',
        b" " * (1024 * 1024 + 1),
    ],
)
def test_strict_request_decoder(data: bytes) -> None:
    with pytest.raises(ValueError):
        decode_request(data)


def test_query_ranges() -> None:
    now = datetime.now(timezone.utc)
    with pytest.raises(ValidationError):
        AuditQuery(start=now - timedelta(days=91), end=now, limit=50)
    with pytest.raises(ValidationError):
        AuditQuery(start=now - timedelta(days=1), end=now, limit=101)
    with pytest.raises(ValidationError):
        UsageQuery(start=now - timedelta(days=91), end=now)
    with pytest.raises(ValidationError):
        UsageQuery(start=now - timedelta(days=1), end=now + timedelta(days=1))


def test_disabled_config_uses_static_branding(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "ORGMESH_ENTERPRISE_BRANDING_ENABLED",
        "ORGMESH_ENTERPRISE_AUDIT_ENABLED",
        "ORGMESH_ENTERPRISE_USAGE_ENABLED",
        "ORGMESH_ENTERPRISE_STATIC_BRANDING_FILE",
    ):
        monkeypatch.delenv(key, raising=False)
    config = EnterpriseConfig.from_env()
    assert (
        not config.branding_enabled
        and not config.audit_enabled
        and not config.usage_enabled
    )
    view = load_static_branding(config)
    assert (view.name, view.greeting, view.logo_asset_id, view.source) == (
        "OrgMesh",
        "",
        "orgmesh-default",
        "static",
    )


def test_enable_multitenant_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MULTI_TENANT", "true")
    monkeypatch.setenv("ORGMESH_ENTERPRISE_BRANDING_ENABLED", "true")
    with pytest.raises(ValueError):
        EnterpriseConfig.from_env()


def test_identity_exact_version() -> None:
    from onyx.orgmesh_enterprise.models import TrustedIdentity

    fixture = json.loads((FIXTURES / "legal.json").read_text())
    fixture["identity"]["version"] = True
    with pytest.raises(ValidationError):
        TrustedIdentity.model_validate_json(json.dumps(fixture["identity"]))


def test_public_body_size_limit() -> None:
    from contextlib import AsyncExitStack

    from fastapi import FastAPI
    from fastapi.routing import APIRoute
    from starlette.requests import Request

    from onyx.error_handling.exceptions import OnyxError
    from onyx.server.features.orgmesh_enterprise.api import router

    application = FastAPI()
    application.include_router(router, prefix="/api")
    route = next(
        route
        for route in application.routes
        if isinstance(route, APIRoute)
        and route.path == "/api/orgmesh-enterprise/v1/branding"
        and "PATCH" in route.methods
    )
    chunks = iter(
        [{"type": "http.request", "body": b"x" * (1024 * 1024 + 1), "more_body": False}]
    )

    async def receive():
        return next(chunks)

    request = Request(
        {
            "type": "http",
            "method": "PATCH",
            "path": route.path,
            "headers": [(b"content-type", b"application/json")],
            "query_string": b"",
            "fastapi_middleware_astack": AsyncExitStack(),
            "fastapi_inner_astack": AsyncExitStack(),
        },
        receive=receive,
    )
    coroutine = route.get_route_handler()(request)
    with pytest.raises(OnyxError) as exc:
        coroutine.send(None)
    assert exc.value.status_code == 413


def test_static_file_rejects_remote_assets(tmp_path: Path) -> None:
    file = tmp_path / "branding.json"
    file.write_text(
        json.dumps(
            {
                "name": "OrgMesh",
                "greeting": "",
                "logo_asset_id": "https://example.com/logo",
            }
        )
    )
    with pytest.raises(ValidationError):
        load_static_branding(EnterpriseConfig(static_branding_file=str(file)))


def test_public_query_unknown_fields_rejected() -> None:
    import asyncio
    from contextlib import AsyncExitStack

    from fastapi import FastAPI
    from fastapi.routing import APIRoute
    from starlette.requests import Request

    from onyx.db.models import User
    from onyx.error_handling.exceptions import OnyxError
    from onyx.server.features.orgmesh_enterprise.api import admin_user, router

    application = FastAPI()
    application.include_router(router)

    async def authenticated_user():
        return User()

    application.dependency_overrides[admin_user] = authenticated_user
    route = next(
        route
        for route in application.routes
        if isinstance(route, APIRoute) and route.path.endswith("/audit/events")
    )

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": route.path,
            "headers": [],
            "query_string": b"tenant_id=attacker",
            "fastapi_middleware_astack": AsyncExitStack(),
            "fastapi_inner_astack": AsyncExitStack(),
            "fastapi_function_astack": AsyncExitStack(),
        },
        receive=receive,
    )
    with pytest.raises(OnyxError) as exc:
        asyncio.run(route.get_route_handler()(request))
    assert exc.value.status_code == 422


def test_route_query_validation_returns_422(monkeypatch: pytest.MonkeyPatch) -> None:
    from onyx.db.models import User
    from onyx.error_handling.exceptions import OnyxError
    from onyx.server.features.orgmesh_enterprise import api

    now = datetime.now(timezone.utc)
    monkeypatch.setattr(api, "get_config", lambda: EnterpriseConfig(audit_enabled=True))
    with pytest.raises(OnyxError) as exc:
        api.get_audit_events(start=now - timedelta(days=91), end=now, user=User())
    assert exc.value.status_code == 422


def test_usage_contract_requires_explicit_metadata() -> None:
    from onyx.orgmesh_enterprise.models import UsageSummary

    with pytest.raises(ValidationError):
        UsageSummary.model_validate({"status": "unavailable"})
    with pytest.raises(ValidationError):
        UsageSummary.model_validate({"status": "unavailable", "estimated_cost": 0.1})


def test_identity_rejects_mixed_timezone_values() -> None:
    from onyx.orgmesh_enterprise.models import TrustedIdentity

    fixture = json.loads((FIXTURES / "legal.json").read_text())
    fixture["identity"]["issued_at"] = "2026-10-12T10:00:00"
    with pytest.raises(ValidationError):
        TrustedIdentity.model_validate_json(json.dumps(fixture["identity"]))


def test_json_schema_matches_shared_boundaries() -> None:
    import jsonschema

    schema = json.loads((FIXTURES.parent / "v1.schema.json").read_text())
    validator = jsonschema.Draft202012Validator(
        schema, format_checker=jsonschema.FormatChecker()
    )
    validator.check_schema(schema)
    validator.validate(json.loads((FIXTURES / "legal.json").read_text()))
    # A wrong tenant is syntactically legal, but identity validation must refuse it.
    validator.validate(json.loads((FIXTURES / "unauthorized.json").read_text()))
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(json.loads((FIXTURES / "overlimit.json").read_text()))


def test_static_file_contains_only_reviewed_branding_fields(tmp_path: Path) -> None:
    file = tmp_path / "branding.json"
    file.write_text(
        json.dumps(
            {
                "name": "OrgMesh Workspace",
                "greeting": "Welcome",
                "logo_asset_id": "orgmesh-default",
            }
        )
    )
    view = load_static_branding(EnterpriseConfig(static_branding_file=str(file)))
    assert (view.name, view.greeting, view.version, view.source) == (
        "OrgMesh Workspace",
        "Welcome",
        0,
        "static",
    )


def test_enable_wrong_tenant_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR

    monkeypatch.setenv("ORGMESH_ENTERPRISE_BRANDING_ENABLED", "true")
    token = CURRENT_TENANT_ID_CONTEXTVAR.set("other")
    try:
        with pytest.raises(ValueError):
            EnterpriseConfig.from_env()
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(token)


def test_json_schema_enforces_logo_whitelist() -> None:
    import jsonschema

    schema = json.loads((FIXTURES.parent / "v1.schema.json").read_text())
    fixture = json.loads((FIXTURES / "overlimit.json").read_text())
    fixture["request"]["patch"]["name"] = "OrgMesh"
    fixture["request"]["patch"]["logo_asset_id"] = "https://example.com/logo"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft202012Validator(schema).validate(fixture)


@pytest.mark.parametrize("field", ["NAME", "Name", "LOGO_ASSET_ID"])
def test_python_rejects_json_field_alias_collisions(field: str) -> None:
    payload = {
        "expected_version": 0,
        "name": "OrgMesh",
        "greeting": "",
        "logo_asset_id": "orgmesh-default",
        field: "Override",
    }
    with pytest.raises(ValidationError):
        BrandingPatch.model_validate_json(json.dumps(payload))


def test_static_view_has_no_persisted_version() -> None:
    assert load_static_branding(EnterpriseConfig()).version == 0


def test_capabilities_keeps_static_contract_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from onyx.server.features.orgmesh_enterprise import api

    monkeypatch.setattr(api, "get_config", lambda: EnterpriseConfig())
    assert api.get_capabilities().static_branding_version == 1


@pytest.mark.parametrize("fields", [{"action": "usage.read"}, {"result": "failure"}])
def test_audit_filters_reject_other_categories(fields: dict[str, str]) -> None:
    now = datetime.now(timezone.utc)
    with pytest.raises(ValidationError):
        AuditQuery.model_validate(
            {"start": now - timedelta(days=1), "end": now, **fields}
        )


def test_audit_filters_round_trip() -> None:
    now = datetime.now(timezone.utc)
    query = AuditQuery(
        start=now - timedelta(days=1),
        end=now,
        action="branding.updated",
        result="success",
    )
    assert query.model_dump()["action"] == "branding.updated"
    assert query.model_dump()["result"] == "success"


@pytest.mark.parametrize("source,version", [("static", 1), ("dynamic", 0)])
def test_branding_response_rejects_inconsistent_source_version(
    source: str, version: int
) -> None:
    from onyx.orgmesh_enterprise.models import BrandingView

    with pytest.raises(ValidationError):
        BrandingView.model_validate(
            {
                "name": "OrgMesh",
                "greeting": "",
                "logo_asset_id": "orgmesh-default",
                "source": source,
                "version": version,
            }
        )


def test_audit_record_has_minimal_resource_identity() -> None:
    from onyx.orgmesh_enterprise.models import AuditEvent

    event = AuditEvent.model_validate_json(
        json.dumps(
            {
                "event_id": "11111111-1111-4111-8111-111111111111",
                "created_at": "2026-10-12T10:00:00Z",
                "user_id": "11111111-1111-4111-8111-111111111111",
                "actor_kind": "user",
                "resource_id": "branding-config",
                "action": "branding.created",
                "result": "success",
                "before_version": 0,
                "after_version": 1,
                "changed_fields": ["name", "greeting", "logo_asset_id"],
                "request_id": "22222222-2222-4222-8222-222222222222",
            }
        )
    )
    assert event.resource_id == "branding-config"
    assert event.actor_kind == "user"


@pytest.mark.parametrize(
    "changes",
    [
        {"after_version": 4},
        {"created_at": "2026-10-12T10:00:00"},
        {"changed_fields": ["name", "name"]},
        {"changed_fields": []},
    ],
)
def test_audit_event_rejects_inconsistent_record(changes: dict[str, object]) -> None:
    from onyx.orgmesh_enterprise.models import AuditEvent

    record: dict[str, object] = {
        "event_id": "11111111-1111-4111-8111-111111111111",
        "created_at": "2026-10-12T10:00:00Z",
        "user_id": "11111111-1111-4111-8111-111111111111",
        "actor_kind": "user",
        "resource_id": "branding-config",
        "action": "branding.created",
        "result": "success",
        "before_version": 0,
        "after_version": 1,
        "changed_fields": ["name", "greeting", "logo_asset_id"],
        "request_id": "22222222-2222-4222-8222-222222222222",
    }
    record.update(changes)
    with pytest.raises(ValidationError):
        AuditEvent.model_validate_json(json.dumps(record))
