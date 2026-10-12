"""Offline recovery checks. Real app, socket, and database acceptance are separate."""

import importlib.abc
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch
from uuid import UUID

import pytest


class DenyEnterpriseImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname: str, path: Any = None, target: Any = None) -> None:  # noqa: ARG002 -- import hook signature
        if fullname == "ee" or fullname.startswith("ee."):
            raise AssertionError(f"new route attempted forbidden import: {fullname}")


def run_http_probe() -> None:
    # Install this before importing the real Community permission gate and routes.
    sys.meta_path.insert(0, DenyEnterpriseImports())
    import httpx
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from onyx.db.enums import AccountType, Permission
    from onyx.db.models import User
    from onyx.error_handling.exceptions import register_onyx_exception_handlers
    from onyx.orgmesh_enterprise.client import EnterpriseClient
    from onyx.orgmesh_enterprise.config import EnterpriseConfig
    from onyx.server.features.orgmesh_enterprise import api

    user = User(
        id=UUID("11111111-1111-4111-8111-111111111111"),
        email="admin@example.test",
        is_active=True,
        is_verified=True,
        account_type=AccountType.STANDARD,
        effective_permissions=[Permission.FULL_ADMIN_PANEL_ACCESS.value],
    )
    application = FastAPI()
    application.include_router(api.router, prefix="/api")
    register_onyx_exception_handlers(application)
    application.dependency_overrides[api.admin_user] = lambda: user
    requests: list[httpx.Request] = []
    brand = {
        "name": "Recovery brand",
        "greeting": "",
        "logo_asset_id": "orgmesh-default",
        "version": 1,
        "source": "dynamic",
    }
    fixture_root = (
        Path(__file__).resolve().parents[4] / "contracts/orgmesh-enterprise/fixtures"
    )

    def upstream(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        body = json.loads(request.content)
        operation = body["request"]["operation"]
        if operation.startswith("branding."):
            response = {"operation": operation, "branding": brand}
        elif operation == "audit.list":
            response = {
                "operation": operation,
                "page": {"events": [], "next_cursor": None},
            }
        else:
            response = json.loads((fixture_root / "usage-summary.json").read_text())
        return httpx.Response(200, json=response)

    config = EnterpriseConfig(
        branding_enabled=True, audit_enabled=True, usage_enabled=True
    )
    client = EnterpriseClient(config, transport=httpx.MockTransport(upstream))
    with (
        patch.object(api, "get_config", return_value=config),
        patch.object(api, "get_client", return_value=client),
        TestClient(application) as browser,
    ):
        base = "/api/orgmesh-enterprise/v1"
        assert browser.get(f"{base}/capabilities").status_code == 200
        assert browser.get(f"{base}/context").status_code == 200
        assert browser.get(f"{base}/branding").json() == brand
        assert (
            browser.patch(
                f"{base}/branding",
                json={
                    "expected_version": 0,
                    "name": "Recovery brand",
                    "greeting": "",
                    "logo_asset_id": "orgmesh-default",
                },
                headers={
                    "Idempotency-Key": "22222222-2222-4222-8222-222222222222",
                    "X-Tenant-ID": "attacker",
                    "X-Role": "admin",
                },
            ).status_code
            == 200
        )
        assert browser.get(f"{base}/audit/events").status_code == 200
        assert browser.get(f"{base}/usage/summary").status_code == 200
        assert (
            browser.get(f"{base}/usage/summary?tenant_id=attacker").status_code == 422
        )
    assert len(requests) == 4
    for request in requests:
        assert request.method == "POST"
        assert str(request.url) == "http://orgmesh-enterprise/v1/call"
        assert "x-tenant-id" not in request.headers
        assert "x-role" not in request.headers
        assert json.loads(request.content)["identity"]["tenant_id"] == "public"
    assert not any(name == "ee" or name.startswith("ee.") for name in sys.modules)
    print(
        "PASS: six real BFF paths, four private HTTP calls, no ee imports or legacy HTTP calls"
    )


def test_new_path_no_ee_import_or_http_call() -> None:
    result = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--probe"],
        capture_output=True,
        text=True,
        timeout=45,
        check=False,
        env=os.environ
        | {"LICENSE_ENFORCEMENT_ENABLED": "false", "MULTI_TENANT": "false"},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "six real BFF paths" in result.stdout


def test_disabled_features_no_source_reads(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from onyx.error_handling.exceptions import register_onyx_exception_handlers
    from onyx.orgmesh_enterprise import snapshot
    from onyx.orgmesh_enterprise.config import EnterpriseConfig
    from onyx.server.features.orgmesh_enterprise import api

    def forbidden(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("disabled feature read a source or called Go")

    monkeypatch.setattr(api, "get_config", lambda: EnterpriseConfig())
    monkeypatch.setattr(api, "get_client", forbidden)
    monkeypatch.setattr(snapshot, "read_usage_snapshot", forbidden)
    snapshot.publish_usage_snapshot(tenant_id="public", config=EnterpriseConfig())
    app = FastAPI()
    app.include_router(api.router, prefix="/api")
    register_onyx_exception_handlers(app)
    app.dependency_overrides[api.admin_user] = lambda: None
    with TestClient(app) as browser:
        base = "/api/orgmesh-enterprise/v1"
        assert browser.get(f"{base}/branding").json()["source"] == "static"
        assert browser.get(f"{base}/audit/events").status_code == 503
        assert browser.get(f"{base}/usage/summary").status_code == 503
        assert (
            browser.patch(
                f"{base}/branding",
                json={
                    "expected_version": 0,
                    "name": "Blocked",
                    "greeting": "",
                    "logo_asset_id": "orgmesh-default",
                },
                headers={"Idempotency-Key": "22222222-2222-4222-8222-222222222222"},
            ).status_code
            == 503
        )


def test_outage_keeps_public_static_branding(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import httpx
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from onyx.orgmesh_enterprise.client import EnterpriseClient
    from onyx.orgmesh_enterprise.config import EnterpriseConfig
    from onyx.server.features.orgmesh_enterprise import api

    static = tmp_path / "branding.json"
    static.write_text(
        '{"name":"Approved static brand","greeting":"Welcome","logo_asset_id":"orgmesh-default"}'
    )
    config = EnterpriseConfig(branding_enabled=True, static_branding_file=str(static))

    def unavailable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("private Go service is stopped", request=request)

    monkeypatch.setattr(api, "get_config", lambda: config)
    monkeypatch.setattr(
        api,
        "get_client",
        lambda: EnterpriseClient(config, transport=httpx.MockTransport(unavailable)),
    )
    app = FastAPI()
    app.include_router(api.router, prefix="/api")
    with TestClient(app) as browser:
        response = browser.get("/api/orgmesh-enterprise/v1/branding")
        assert response.status_code == 200
        assert response.json() == {
            "name": "Approved static brand",
            "greeting": "Welcome",
            "logo_asset_id": "orgmesh-default",
            "version": 0,
            "source": "static",
        }


if __name__ == "__main__":
    run_http_probe()
