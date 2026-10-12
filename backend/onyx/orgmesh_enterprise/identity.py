# SPDX-License-Identifier: MIT
"""Create short-lived context only after community authentication and permission checks."""

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid5

from onyx.auth.permissions import has_global_permission
from onyx.auth.users import user_needs_to_be_verified
from onyx.db.enums import Permission
from onyx.db.models import User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.orgmesh_enterprise.config import EnterpriseConfig
from onyx.orgmesh_enterprise.models import EnterpriseOperation, TrustedIdentity
from shared_configs.contextvars import get_current_tenant_id

_REQUEST_NAMESPACE = UUID("f7c7ecef-feba-4a1b-8797-4d0b76d7863e")


def configured_tenant() -> str:
    try:
        config = EnterpriseConfig.from_env()
    except ValueError as error:
        raise OnyxError(OnyxErrorCode.SINGLE_TENANT_ONLY) from error
    tenant = get_current_tenant_id()
    if tenant != config.tenant_id:
        raise OnyxError(OnyxErrorCode.SINGLE_TENANT_ONLY)
    return tenant


def derive_request_id(
    key: UUID, user_id: UUID, tenant: str, operation: EnterpriseOperation
) -> UUID:
    import json

    return uuid5(
        _REQUEST_NAMESPACE,
        json.dumps(
            [tenant, str(user_id), operation.value, str(key)], separators=(",", ":")
        ),
    )


def authorize_enterprise_operation(
    user: User, operation: EnterpriseOperation, request_id: UUID
) -> TrustedIdentity:
    if (
        not user.is_active
        or (user_needs_to_be_verified() and not user.is_verified)
        or not has_global_permission(user, Permission.FULL_ADMIN_PANEL_ACCESS)
    ):
        raise OnyxError(OnyxErrorCode.INSUFFICIENT_PERMISSIONS)
    now = datetime.now(timezone.utc)
    return TrustedIdentity(
        tenant_id=configured_tenant(),
        actor_kind="user",
        user_id=user.id,
        operation=operation,
        request_id=request_id,
        issued_at=now,
        expires_at=now + timedelta(seconds=5),
    )


def anonymous_branding_identity(request_id: UUID) -> TrustedIdentity:
    now = datetime.now(timezone.utc)
    return TrustedIdentity(
        tenant_id=configured_tenant(),
        actor_kind="anonymous",
        user_id="",
        operation=EnterpriseOperation.BRANDING_READ,
        request_id=request_id,
        issued_at=now,
        expires_at=now + timedelta(seconds=5),
    )
