"""Use the community permission gate, including its PAT scope cap."""

from uuid import UUID, uuid4

import pytest
from starlette.requests import Request
from starlette.responses import Response

from onyx.db.enums import AccountType, Permission
from onyx.db.models import User
from onyx.error_handling.exceptions import OnyxError
from onyx.orgmesh_enterprise.identity import (
    authorize_enterprise_operation,
    derive_request_id,
)
from onyx.orgmesh_enterprise.models import EnterpriseOperation
from onyx.server.features.orgmesh_enterprise.api import admin_user


def admin() -> User:
    return User(
        id=UUID("11111111-1111-4111-8111-111111111111"),
        email="admin@example.test",
        is_active=True,
        is_verified=True,
        account_type=AccountType.STANDARD,
        effective_permissions=[Permission.FULL_ADMIN_PANEL_ACCESS.value],
    )


def test_pat_scope_denied() -> None:
    request = Request({"type": "http", "headers": []})
    request.state.token_scopes = [Permission.READ_SEARCH]
    coroutine = admin_user(request=request, user=admin())
    with pytest.raises(OnyxError) as exc:
        coroutine.send(None)
    assert exc.value.status_code == 403


def test_verified_global_admin_identity() -> None:
    identity = authorize_enterprise_operation(
        admin(), EnterpriseOperation.BRANDING_PATCH, uuid4()
    )
    assert identity.tenant_id == "public"
    assert identity.actor_kind == "user"
    assert identity.operation == "branding.patch"
    assert identity.audience == "orgmesh-enterprise/v1"
    assert (identity.expires_at - identity.issued_at).total_seconds() == 5


@pytest.mark.parametrize("field", ["is_active", "is_verified"])
def test_unverified_user_denied(field: str, monkeypatch: pytest.MonkeyPatch) -> None:
    from onyx.auth import users

    monkeypatch.setattr(users, "REQUIRE_EMAIL_VERIFICATION", True)
    user = admin()
    if field == "is_active":
        user.is_active = False
    else:
        user.is_verified = False
    with pytest.raises(OnyxError):
        authorize_enterprise_operation(
            user, EnterpriseOperation.BRANDING_PATCH, uuid4()
        )


def test_non_admin_denied() -> None:
    user = admin()
    user.effective_permissions = [Permission.MANAGE_USER_GROUPS.value]
    with pytest.raises(OnyxError):
        authorize_enterprise_operation(user, EnterpriseOperation.AUDIT_LIST, uuid4())


def test_idempotency_identity_binds_tenant_user_operation() -> None:
    key = UUID("22222222-2222-4222-8222-222222222222")
    actor = UUID("11111111-1111-4111-8111-111111111111")
    result = derive_request_id(key, actor, "public", EnterpriseOperation.BRANDING_PATCH)
    assert result == derive_request_id(
        key, actor, "public", EnterpriseOperation.BRANDING_PATCH
    )
    assert result != derive_request_id(
        key, actor, "other", EnterpriseOperation.BRANDING_PATCH
    )
    assert result != derive_request_id(
        key, uuid4(), "public", EnterpriseOperation.BRANDING_PATCH
    )
    assert result != derive_request_id(
        key, actor, "public", EnterpriseOperation.AUDIT_LIST
    )


@pytest.mark.parametrize("prefix", ["", "api"])
def test_disabled_enterprise_routes_pass_startup_auth_check(
    monkeypatch: pytest.MonkeyPatch, prefix: str
) -> None:
    from fastapi import FastAPI

    from onyx.server import auth_check
    from onyx.server.features.orgmesh_enterprise import api

    for key in (
        "ORGMESH_ENTERPRISE_BRANDING_ENABLED",
        "ORGMESH_ENTERPRISE_AUDIT_ENABLED",
        "ORGMESH_ENTERPRISE_USAGE_ENABLED",
    ):
        monkeypatch.setenv(key, "false")
    monkeypatch.setattr(auth_check, "APP_API_PREFIX", prefix)
    application = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
    application.include_router(api.router, prefix=f"/{prefix}" if prefix else "")
    auth_check.check_router_auth(application)
    capabilities = api.get_capabilities()
    assert capabilities.model_dump() == {
        "branding_enabled": False,
        "audit_enabled": False,
        "usage_enabled": False,
        "static_branding_version": 1,
    }
    assert api.get_branding().source == "static"


@pytest.mark.parametrize(
    ("path", "method"),
    [
        ("/branding", "PATCH"),
        ("/audit/events", "GET"),
        ("/usage/summary", "GET"),
        ("/capabilities", "POST"),
        ("/internal", "GET"),
    ],
)
def test_enterprise_public_whitelist_does_not_admit_private_routes(
    path: str, method: str
) -> None:
    from fastapi import FastAPI

    from onyx.server.auth_check import check_router_auth

    application = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)

    async def unguarded() -> dict[str, str]:
        return {"status": "unguarded"}

    application.add_api_route(
        f"/orgmesh-enterprise/v1{path}", unguarded, methods=[method]
    )
    with pytest.raises(RuntimeError, match="Did not find user dependency"):
        check_router_auth(application)


def test_enterprise_admin_routes_pass_auth_check_without_public_exemptions() -> None:
    from fastapi import FastAPI
    from fastapi.routing import APIRoute

    from onyx.server.auth_check import check_router_auth
    from onyx.server.features.orgmesh_enterprise.api import router

    application = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
    application.include_router(router)
    public_paths = {
        "/orgmesh-enterprise/v1/branding",
        "/orgmesh-enterprise/v1/capabilities",
    }
    application.router.routes = [
        route
        for route in application.routes
        if not (
            isinstance(route, APIRoute)
            and route.path in public_paths
            and route.methods == {"GET"}
        )
    ]
    assert len(application.routes) == 4
    check_router_auth(application, public_endpoint_specs=[])


def test_unverified_admin_allowed_when_community_verification_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from onyx.auth import users

    monkeypatch.setattr(users, "REQUIRE_EMAIL_VERIFICATION", False)
    user = admin()
    user.is_verified = False
    identity = authorize_enterprise_operation(
        user, EnterpriseOperation.BRANDING_PATCH, uuid4()
    )
    assert identity.user_id == user.id


def context_route():
    from fastapi.routing import APIRoute

    from onyx.server.features.orgmesh_enterprise.api import router

    route = next(
        (
            route
            for route in router.routes
            if isinstance(route, APIRoute)
            and route.path == "/orgmesh-enterprise/v1/context"
        ),
        None,
    )
    assert route is not None, "authenticated organization context route is missing"
    return route


def test_context_returns_only_verified_actor_and_configured_tenant() -> None:
    route = context_route()
    user = admin()
    assert route.endpoint(response=Response(), user=user).model_dump(mode="json") == {
        "user_id": "11111111-1111-4111-8111-111111111111",
        "tenant_id": "public",
    }


def test_context_requires_actual_full_admin_dependency() -> None:
    route = context_route()
    assert [dependency.call for dependency in route.dependant.dependencies] == [
        admin_user
    ]
    user = admin()
    user.effective_permissions = [Permission.MANAGE_USER_GROUPS.value]
    request = Request({"type": "http", "headers": []})
    with pytest.raises(OnyxError) as error:
        admin_user(request=request, user=user).send(None)
    assert error.value.status_code == 403


def test_context_restricted_pat_is_denied() -> None:
    route = context_route()
    request = Request({"type": "http", "headers": []})
    request.state.token_scopes = [Permission.READ_SEARCH]
    with pytest.raises(OnyxError) as error:
        route.dependant.dependencies[0].call(request=request, user=admin()).send(None)
    assert error.value.status_code == 403


def test_context_rejects_other_configured_organization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    route = context_route()
    monkeypatch.setenv("ORGMESH_ENTERPRISE_TENANT_ID", "another")
    with pytest.raises(OnyxError):
        route.endpoint(response=Response(), user=admin())


def test_context_is_not_a_public_startup_exemption() -> None:
    from fastapi import FastAPI

    from onyx.server.auth_check import check_router_auth

    context_route()
    application = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)

    def unguarded() -> dict[str, str]:
        return {"status": "unguarded"}

    application.add_api_route("/orgmesh-enterprise/v1/context", unguarded)
    with pytest.raises(RuntimeError, match="Did not find user dependency"):
        check_router_auth(application)


def test_context_response_is_private_and_ignores_browser_tenant_headers() -> None:
    import asyncio

    import httpx
    from fastapi import FastAPI

    from onyx.auth.users import current_user
    from onyx.server.features.orgmesh_enterprise.api import router

    application = FastAPI()
    application.include_router(router)
    application.dependency_overrides[current_user] = admin

    async def request_context() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application),
            base_url="http://isolated.test",
        ) as client:
            return await client.get(
                "/orgmesh-enterprise/v1/context",
                headers={"X-Tenant-ID": "untrusted", "X-User-ID": "untrusted"},
            )

    response = asyncio.run(request_context())
    assert response.status_code == 200
    assert response.json() == {
        "user_id": "11111111-1111-4111-8111-111111111111",
        "tenant_id": "public",
    }
    assert response.headers["cache-control"] == "no-store"
