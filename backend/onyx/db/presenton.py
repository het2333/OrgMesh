"""Resolve the platform model for presentation generation."""

from sqlalchemy.orm import Session

from onyx.auth.permissions import has_global_permission
from onyx.db.enums import Permission
from onyx.db.llm import fetch_accessible_llm_provider_by_id, fetch_default_llm_model
from onyx.db.models import User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.manage.llm.models import LLMProviderView


def presentation_model(db_session: Session, user: User) -> tuple[str, LLMProviderView]:
    if not user.is_active or not has_global_permission(user, Permission.BASIC_ACCESS):
        raise OnyxError(OnyxErrorCode.INSUFFICIENT_PERMISSIONS)
    model = fetch_default_llm_model(db_session)
    if model is None or not model.is_visible:
        raise OnyxError(
            OnyxErrorCode.SERVICE_UNAVAILABLE, "Configure an available default model"
        )
    provider = fetch_accessible_llm_provider_by_id(
        db_session, user, model.llm_provider_id
    )
    if provider is None:
        raise OnyxError(
            OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
            "Default model is not available to this user",
        )
    return model.name, provider
