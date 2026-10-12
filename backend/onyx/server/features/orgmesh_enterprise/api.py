# SPDX-License-Identifier: MIT
"""Public BFF for the independent private service."""

from collections.abc import Callable, Coroutine
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.routing import APIRoute
from pydantic import ValidationError
from starlette.responses import Response
from starlette.types import Message

from onyx.auth.permissions import require_permission
from onyx.db.enums import Permission
from onyx.db.models import User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.orgmesh_enterprise.client import EnterpriseClient
from onyx.orgmesh_enterprise.config import EnterpriseConfig, load_static_branding
from onyx.orgmesh_enterprise.identity import (
    anonymous_branding_identity,
    authorize_enterprise_operation,
    configured_tenant,
    derive_request_id,
)
from onyx.orgmesh_enterprise.models import (
    MAX_BYTES,
    AuditListRequest,
    AuditListResponse,
    AuditPage,
    AuditQuery,
    BrandingPatch,
    BrandingPatchRequest,
    BrandingPatchResponse,
    BrandingReadRequest,
    BrandingReadResponse,
    BrandingView,
    ContractModel,
    EnterpriseContext,
    EnterpriseOperation,
    UsageQuery,
    UsageSummary,
    UsageSummaryRequest,
    UsageSummaryResponse,
    validate_json_bytes,
)


class BoundedEnterpriseRoute(APIRoute):
    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original = super().get_route_handler()
        allowed_queries = {field.alias for field in self.dependant.query_params}

        async def bounded(request: Request) -> Response:
            if set(request.query_params) - allowed_queries:
                raise OnyxError(
                    OnyxErrorCode.VALIDATION_ERROR,
                    status_code_override=HTTPStatus.UNPROCESSABLE_ENTITY,
                )
            body = bytearray()
            async for chunk in request.stream():
                if len(body) + len(chunk) > MAX_BYTES:
                    raise OnyxError(OnyxErrorCode.PAYLOAD_TOO_LARGE)
                body.extend(chunk)
            if body:
                try:
                    validate_json_bytes(bytes(body))
                except ValueError as error:
                    raise OnyxError(
                        OnyxErrorCode.VALIDATION_ERROR,
                        status_code_override=HTTPStatus.UNPROCESSABLE_ENTITY,
                    ) from error
            received = False

            async def receive() -> Message:
                nonlocal received
                if received:
                    return await request.receive()
                received = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}

            return await original(Request(request.scope, receive=receive))

        return bounded


router = APIRouter(
    prefix="/orgmesh-enterprise/v1",
    tags=["orgmesh-enterprise"],
    route_class=BoundedEnterpriseRoute,
)
admin_user = require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)


def get_config() -> EnterpriseConfig:
    try:
        return EnterpriseConfig.from_env()
    except ValueError as error:
        raise OnyxError(OnyxErrorCode.DEPLOYMENT_UNSUPPORTED) from error


def get_client() -> EnterpriseClient:
    return EnterpriseClient(get_config())


class Capabilities(ContractModel):
    branding_enabled: bool
    audit_enabled: bool
    usage_enabled: bool
    static_branding_version: int


@router.get("/capabilities")
def get_capabilities() -> Capabilities:
    config = get_config()
    return Capabilities(
        branding_enabled=config.branding_enabled,
        audit_enabled=config.audit_enabled,
        usage_enabled=config.usage_enabled,
        static_branding_version=1,
    )


@router.get("/context")
def get_enterprise_context(
    response: Response, user: User = Depends(admin_user)
) -> EnterpriseContext:
    identity = authorize_enterprise_operation(
        user, EnterpriseOperation.AUDIT_LIST, uuid4()
    )
    response.headers["Cache-Control"] = "no-store"
    return EnterpriseContext(user_id=user.id, tenant_id=identity.tenant_id)


@router.get("/branding")
def get_branding() -> BrandingView:
    config = get_config()
    static = load_static_branding(config)
    if not config.branding_enabled:
        return static
    try:
        result = get_client().call(
            EnterpriseOperation.BRANDING_READ,
            anonymous_branding_identity(uuid4()),
            BrandingReadRequest(),
        )
    except OnyxError:
        return static
    if not isinstance(result, BrandingReadResponse):
        return static
    return result.branding


@router.patch("/branding")
def patch_branding(
    patch: BrandingPatch,
    _request: Request,
    idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
    user: User = Depends(admin_user),
) -> BrandingView:
    if not get_config().branding_enabled:
        raise OnyxError(OnyxErrorCode.SERVICE_UNAVAILABLE)
    request_id = derive_request_id(
        idempotency_key,
        user.id,
        configured_tenant(),
        EnterpriseOperation.BRANDING_PATCH,
    )
    identity = authorize_enterprise_operation(
        user, EnterpriseOperation.BRANDING_PATCH, request_id
    )
    result = get_client().call(
        EnterpriseOperation.BRANDING_PATCH, identity, BrandingPatchRequest(patch=patch)
    )
    if not isinstance(result, BrandingPatchResponse):
        raise OnyxError(OnyxErrorCode.SERVICE_UNAVAILABLE)
    return result.branding


@router.get("/audit/events")
def get_audit_events(
    start: datetime | None = None,
    end: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: Annotated[str, Query(max_length=512)] = "",
    action: Literal["", "branding.created", "branding.updated"] = "",
    result: Literal["", "success"] = "",
    user: User = Depends(admin_user),
) -> AuditPage:
    if not get_config().audit_enabled:
        raise OnyxError(OnyxErrorCode.SERVICE_UNAVAILABLE)
    last = end or datetime.now(timezone.utc)
    try:
        query = AuditQuery(
            start=start or last - timedelta(days=30),
            end=last,
            limit=limit,
            cursor=cursor,
            action=action,
            result=result,
        )
    except ValidationError as error:
        raise OnyxError(
            OnyxErrorCode.VALIDATION_ERROR,
            status_code_override=HTTPStatus.UNPROCESSABLE_ENTITY,
        ) from error
    identity = authorize_enterprise_operation(
        user, EnterpriseOperation.AUDIT_LIST, uuid4()
    )
    upstream_response = get_client().call(
        EnterpriseOperation.AUDIT_LIST, identity, AuditListRequest(query=query)
    )
    if not isinstance(upstream_response, AuditListResponse):
        raise OnyxError(OnyxErrorCode.SERVICE_UNAVAILABLE)
    return upstream_response.page


@router.get("/usage/summary")
def usage_summary_route(
    start: datetime | None = None,
    end: datetime | None = None,
    group_by: Literal["day", "model", "flow"] = "day",
    user: User = Depends(admin_user),
) -> UsageSummary:
    if not get_config().usage_enabled:
        raise OnyxError(OnyxErrorCode.SERVICE_UNAVAILABLE)
    today = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    last = end or today + timedelta(days=1)
    try:
        query = UsageQuery(
            start=start or today - timedelta(days=29), end=last, group_by=group_by
        )
    except ValidationError as error:
        raise OnyxError(
            OnyxErrorCode.VALIDATION_ERROR,
            status_code_override=HTTPStatus.UNPROCESSABLE_ENTITY,
        ) from error
    return get_usage_summary(query, user)


def get_usage_summary(query: UsageQuery, user: User) -> UsageSummary:
    if not get_config().usage_enabled:
        raise OnyxError(OnyxErrorCode.SERVICE_UNAVAILABLE)
    identity = authorize_enterprise_operation(
        user, EnterpriseOperation.USAGE_SUMMARY, uuid4()
    )
    result = get_client().call(
        EnterpriseOperation.USAGE_SUMMARY, identity, UsageSummaryRequest(query=query)
    )
    if not isinstance(result, UsageSummaryResponse):
        raise OnyxError(OnyxErrorCode.SERVICE_UNAVAILABLE)
    return result.summary
