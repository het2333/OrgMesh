"""Exercise request serialization with only the unavailable UDS replaced."""

import json
from datetime import timedelta
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest
from starlette.requests import Request

from onyx.db.enums import AccountType, Permission
from onyx.db.models import User
from onyx.error_handling.exceptions import OnyxError
from onyx.orgmesh_enterprise.client import EnterpriseClient
from onyx.orgmesh_enterprise.config import EnterpriseConfig
from onyx.orgmesh_enterprise.models import (
    BrandingPatch,
    BrandingPatchRequest,
    BrandingReadRequest,
    EnterpriseOperation,
)
from onyx.server.features.orgmesh_enterprise import api


def test_routes_use_server_configured_private_socket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = "/tmp/orgmesh-isolated/private/enterprise.sock"
    monkeypatch.setenv("ORGMESH_ENTERPRISE_SOCKET_PATH", path)
    assert api.get_client().config.socket_path == path


@pytest.mark.parametrize(
    "path", ["", "relative.sock", "/tmp/../private/enterprise.sock"]
)
def test_routes_reject_invalid_server_socket_configuration(
    monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    monkeypatch.setenv("ORGMESH_ENTERPRISE_SOCKET_PATH", path)
    with pytest.raises(OnyxError) as error:
        api.get_client()
    assert error.value.status_code == 403


def test_client_identity_headers_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[dict[str, object]] = []

    def upstream(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        assert (
            "x-tenant-id" not in request.headers and "x-user-id" not in request.headers
        )
        return httpx.Response(
            200,
            json={
                "operation": "branding.patch",
                "branding": {
                    "name": "OrgMesh",
                    "greeting": "",
                    "logo_asset_id": "orgmesh-default",
                    "version": 1,
                    "source": "dynamic",
                },
            },
        )

    client = EnterpriseClient(
        EnterpriseConfig(branding_enabled=True), transport=httpx.MockTransport(upstream)
    )
    monkeypatch.setattr(api, "get_client", lambda: client)
    monkeypatch.setattr(
        api, "get_config", lambda: EnterpriseConfig(branding_enabled=True)
    )
    user = User(
        id=UUID("11111111-1111-4111-8111-111111111111"),
        email="admin@example.test",
        is_active=True,
        is_verified=True,
        account_type=AccountType.STANDARD,
        effective_permissions=[Permission.FULL_ADMIN_PANEL_ACCESS.value],
    )
    request = Request(
        {
            "type": "http",
            "headers": [
                (b"x-tenant-id", b"attacker"),
                (b"x-user-id", b"attacker"),
                (b"x-role", b"admin"),
            ],
        }
    )
    result = api.patch_branding(
        BrandingPatch(
            expected_version=0,
            name="OrgMesh",
            greeting="",
            logo_asset_id="orgmesh-default",
        ),
        request,
        UUID("22222222-2222-4222-8222-222222222222"),
        user,
    )
    assert result.source == "dynamic"
    assert sent[0]["identity"]["tenant_id"] == "public"
    assert sent[0]["identity"]["user_id"] == "11111111-1111-4111-8111-111111111111"


def anonymous():
    from onyx.orgmesh_enterprise.identity import anonymous_branding_identity

    return anonymous_branding_identity(uuid4())


def test_client_refreshes_context() -> None:
    identity = anonymous()
    old = identity.model_copy(
        update={
            "issued_at": identity.issued_at - timedelta(seconds=30),
            "expires_at": identity.expires_at - timedelta(seconds=30),
        }
    )

    def upstream(request: httpx.Request) -> httpx.Response:
        value = json.loads(request.content)
        assert value["identity"]["issued_at"] != old.issued_at.isoformat()
        return httpx.Response(
            200,
            json={
                "operation": "branding.read",
                "branding": {
                    "name": "OrgMesh",
                    "greeting": "",
                    "logo_asset_id": "orgmesh-default",
                    "version": 1,
                    "source": "dynamic",
                },
            },
        )

    result = EnterpriseClient(
        EnterpriseConfig(), transport=httpx.MockTransport(upstream)
    ).call(EnterpriseOperation.BRANDING_READ, old, BrandingReadRequest())
    assert result.operation == "branding.read"


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(302, headers={"location": "https://example.test"}),
        httpx.Response(200, content=b"x" * (1024 * 1024 + 1)),
        httpx.Response(
            200,
            json={
                "operation": "audit.list",
                "page": {"events": [], "next_cursor": None},
            },
        ),
        httpx.Response(
            200,
            json={
                "operation": "branding.read",
                "branding": {
                    "name": "OrgMesh",
                    "greeting": "",
                    "logo_asset_id": "orgmesh-default",
                    "version": 1,
                    "source": "dynamic",
                    "secret": "value",
                },
            },
        ),
    ],
)
def test_client_rejects_unsafe_response(response: httpx.Response) -> None:
    client = EnterpriseClient(
        EnterpriseConfig(), transport=httpx.MockTransport(lambda _: response)
    )
    with pytest.raises(OnyxError) as exc:
        client.call(
            EnterpriseOperation.BRANDING_READ, anonymous(), BrandingReadRequest()
        )
    assert exc.value.status_code == 503


def test_client_rejects_cross_operation_context() -> None:
    client = EnterpriseClient(
        EnterpriseConfig(), transport=httpx.MockTransport(lambda _: httpx.Response(200))
    )
    with pytest.raises(OnyxError):
        client.call(
            EnterpriseOperation.BRANDING_PATCH,
            anonymous(),
            BrandingPatchRequest(
                patch=BrandingPatch(
                    expected_version=0,
                    name="OrgMesh",
                    greeting="",
                    logo_asset_id="orgmesh-default",
                )
            ),
        )


def test_branding_outage_returns_static(monkeypatch: pytest.MonkeyPatch) -> None:
    def unavailable(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("unavailable")

    monkeypatch.setattr(
        api, "get_config", lambda: EnterpriseConfig(branding_enabled=True)
    )
    monkeypatch.setattr(
        api,
        "get_client",
        lambda: EnterpriseClient(
            EnterpriseConfig(), transport=httpx.MockTransport(unavailable)
        ),
    )
    result = api.get_branding()
    assert (result.name, result.source) == ("OrgMesh", "static")


def test_client_rejects_compressed_response() -> None:
    import gzip

    value = {
        "operation": "branding.read",
        "branding": {
            "name": "OrgMesh",
            "greeting": "",
            "logo_asset_id": "orgmesh-default",
            "version": 1,
            "source": "dynamic",
        },
    }
    response = httpx.Response(
        200,
        headers={"content-encoding": "gzip"},
        content=gzip.compress(json.dumps(value).encode()),
    )
    client = EnterpriseClient(
        EnterpriseConfig(), transport=httpx.MockTransport(lambda _: response)
    )
    with pytest.raises(OnyxError) as exc:
        client.call(
            EnterpriseOperation.BRANDING_READ, anonymous(), BrandingReadRequest()
        )
    assert exc.value.status_code == 503


def test_transport_has_no_network_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    transport_options: list[dict[str, object]] = []
    client_options: list[dict[str, object]] = []
    real_client = httpx.Client

    def transport(**options):
        transport_options.append(options)
        return httpx.MockTransport(lambda _: httpx.Response(503))

    def configured_client(**options):
        client_options.append(options)
        return real_client(**options)

    monkeypatch.setattr(httpx, "HTTPTransport", transport)
    monkeypatch.setattr(httpx, "Client", configured_client)
    with pytest.raises(OnyxError):
        EnterpriseClient(EnterpriseConfig()).call(
            EnterpriseOperation.BRANDING_READ, anonymous(), BrandingReadRequest()
        )
    assert transport_options == [
        {
            "uds": "/run/orgmesh-enterprise/enterprise.sock",
            "retries": 0,
            "trust_env": False,
        }
    ]
    assert client_options[0]["timeout"] == 2.0
    assert client_options[0]["trust_env"] is False
    assert client_options[0]["follow_redirects"] is False


def test_client_preserves_validation_status() -> None:
    client = EnterpriseClient(
        EnterpriseConfig(), transport=httpx.MockTransport(lambda _: httpx.Response(422))
    )
    with pytest.raises(OnyxError) as exc:
        client.call(
            EnterpriseOperation.BRANDING_READ, anonymous(), BrandingReadRequest()
        )
    assert exc.value.status_code == 422


def test_missing_dynamic_row_preserves_custom_static_branding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    file = tmp_path / "branding.json"
    file.write_text(
        json.dumps(
            {
                "name": "Approved Brand",
                "greeting": "Welcome",
                "logo_asset_id": "orgmesh-default",
            }
        )
    )
    config = EnterpriseConfig(branding_enabled=True, static_branding_file=str(file))
    client = EnterpriseClient(
        config, transport=httpx.MockTransport(lambda _: httpx.Response(503))
    )
    monkeypatch.setattr(api, "get_config", lambda: config)
    monkeypatch.setattr(api, "get_client", lambda: client)
    result = api.get_branding()
    assert (result.name, result.version, result.source) == (
        "Approved Brand",
        0,
        "static",
    )


def test_bff_forwards_audit_filters(monkeypatch: pytest.MonkeyPatch) -> None:
    from datetime import datetime, timezone

    sent: list[dict[str, object]] = []

    def upstream(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content)["request"]["query"])
        return httpx.Response(
            200,
            json={
                "operation": "audit.list",
                "page": {"events": [], "next_cursor": None},
            },
        )

    config = EnterpriseConfig(audit_enabled=True)
    monkeypatch.setattr(api, "get_config", lambda: config)
    monkeypatch.setattr(
        api,
        "get_client",
        lambda: EnterpriseClient(config, transport=httpx.MockTransport(upstream)),
    )
    user = User(
        id=UUID("11111111-1111-4111-8111-111111111111"),
        email="admin@example.test",
        is_active=True,
        is_verified=True,
        account_type=AccountType.STANDARD,
        effective_permissions=[Permission.FULL_ADMIN_PANEL_ACCESS.value],
    )
    now = datetime.now(timezone.utc)
    api.get_audit_events(
        start=now - timedelta(days=1),
        end=now,
        action="branding.updated",
        result="success",
        user=user,
    )
    assert sent[0]["action"] == "branding.updated"
    assert sent[0]["result"] == "success"
