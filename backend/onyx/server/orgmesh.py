import os
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from onyx.access.directory import fetch_feishu_directory
from onyx.auth.permissions import require_permission
from onyx.configs.app_configs import DISABLE_VECTOR_DB
from onyx.configs.constants import DocumentSource
from onyx.connectors.feishu.client import FeishuAPIError, FeishuClient
from onyx.context.search.models import BaseFilters, ChunkSearchRequest
from onyx.context.search.pipeline import search_pipeline
from onyx.db.credentials import fetch_credential_by_id
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import Permission
from onyx.db.models import User
from onyx.db.orgmesh import (
    active_sso_provider_count,
    directory_summary,
    replace_directory_snapshot,
)
from onyx.db.search_settings import get_current_search_settings
from onyx.document_index.factory import get_default_document_index
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.key_value_store.factory import get_kv_store
from onyx.key_value_store.interface import KvKeyNotFoundError
from onyx.server.features.search.models import SearchResult
from onyx.server.utils_vector_db import require_vector_db

router = APIRouter(prefix="/manage/admin/orgmesh")
DIRECTORY_CONFIG_KEY = "orgmesh:directory:config"


class DirectoryConfig(BaseModel):
    enabled: bool = False
    credential_id: int | None = None


def load_directory_config() -> DirectoryConfig:
    try:
        return DirectoryConfig.model_validate(get_kv_store().load(DIRECTORY_CONFIG_KEY))
    except KvKeyNotFoundError:
        return DirectoryConfig()


class EnterpriseStatus(BaseModel):
    search_enabled: bool
    local_demo_access: bool
    sso_providers: int
    directory_config: DirectoryConfig
    directory_users: int
    directory_last_sync: datetime | None
    acl_max_age_seconds: int = 900


@router.get("/status")
def status(
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> EnterpriseStatus:
    users, last_sync = directory_summary(db_session)
    return EnterpriseStatus(
        search_enabled=not DISABLE_VECTOR_DB,
        local_demo_access=os.environ.get("ORGMESH_LOCAL_ACCESS", "false").lower()
        == "true",
        sso_providers=active_sso_provider_count(db_session),
        directory_config=load_directory_config(),
        directory_users=users,
        directory_last_sync=last_sync,
    )


@router.put("/directory")
def save_directory(
    config: DirectoryConfig,
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> DirectoryConfig:
    if config.enabled and config.credential_id is None:
        raise OnyxError(OnyxErrorCode.VALIDATION_ERROR, "Select a Feishu credential")
    if config.credential_id is not None:
        credential = fetch_credential_by_id(config.credential_id, db_session)
        if credential is None or credential.source != DocumentSource.FEISHU:
            raise OnyxError(
                OnyxErrorCode.VALIDATION_ERROR, "Credential must belong to Feishu"
            )
    get_kv_store().store(DIRECTORY_CONFIG_KEY, config.model_dump())
    return config


def synchronize_directory(db_session: Session) -> int:
    config = load_directory_config()
    if not config.enabled or config.credential_id is None:
        raise OnyxError(
            OnyxErrorCode.VALIDATION_ERROR,
            "Configure the Feishu employee directory first",
        )
    credential = fetch_credential_by_id(config.credential_id, db_session)
    if (
        credential is None
        or credential.source != DocumentSource.FEISHU
        or credential.credential_json is None
    ):
        raise OnyxError(
            OnyxErrorCode.VALIDATION_ERROR, "Feishu credential is unavailable"
        )
    data = credential.credential_json.get_value(apply_mask=False)
    client = FeishuClient(
        str(data.get("feishu_app_id", "")), str(data.get("feishu_app_secret", ""))
    )
    try:
        employees = fetch_feishu_directory(client)
        return replace_directory_snapshot(db_session, employees)
    except (FeishuAPIError, ValueError) as error:
        raise OnyxError(
            OnyxErrorCode.BAD_GATEWAY,
            "Feishu directory sync failed; check app scopes and directory errors",
        ) from error


class DirectorySyncResult(BaseModel):
    employees: int


@router.post("/directory/sync")
def sync_directory(
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> DirectorySyncResult:
    return DirectorySyncResult(employees=synchronize_directory(db_session))


runtime_router = APIRouter(prefix="/orgmesh")


class RuntimeMode(BaseModel):
    local_demo_access: bool


@runtime_router.get("/runtime")
def runtime_mode(
    _: User = Depends(require_permission(Permission.BASIC_ACCESS)),
) -> RuntimeMode:
    return RuntimeMode(
        local_demo_access=os.environ.get("ORGMESH_LOCAL_ACCESS", "false").lower()
        == "true"
    )


class WorkspaceSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2048)
    sources: list[DocumentSource] | None = None
    hybrid_alpha: float = Field(default=0.5, ge=0, le=1)
    limit: int = Field(default=20, ge=1, le=50)

    @field_validator("query")
    @classmethod
    def trim_query(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Search query cannot be empty")
        return value


class WorkspaceSearchResult(SearchResult):
    document_id: str
    score: float | None


class WorkspaceSearchResponse(BaseModel):
    results: list[WorkspaceSearchResult]


@runtime_router.post("/search", dependencies=[Depends(require_vector_db)])
def search_workspace(
    request: WorkspaceSearchRequest,
    user: User = Depends(require_permission(Permission.READ_SEARCH)),
    db_session: Session = Depends(get_session),
) -> WorkspaceSearchResponse:
    settings = get_current_search_settings(db_session)
    document_index = get_default_document_index(settings, None, db_session)
    chunks = search_pipeline(
        chunk_search_request=ChunkSearchRequest(
            query=request.query,
            hybrid_alpha=request.hybrid_alpha,
            limit=min(request.limit * 3, 150),
            user_selected_filters=BaseFilters(source_type=request.sources),
        ),
        document_index=document_index,
        user=user,
        persona_search_info=None,
        db_session=db_session,
        force_configured_document_set_scope=True,
    )
    results: list[WorkspaceSearchResult] = []
    seen: set[str] = set()
    for chunk in chunks:
        if chunk.document_id in seen:
            continue
        seen.add(chunk.document_id)
        results.append(
            WorkspaceSearchResult(
                document_id=chunk.document_id,
                citation_id=len(results) + 1,
                title=chunk.title or chunk.semantic_identifier,
                content=chunk.content[:2000],
                link=next(iter((chunk.source_links or {}).values()), None),
                source_type=chunk.source_type.value,
                updated_at=chunk.updated_at.isoformat() if chunk.updated_at else None,
                score=chunk.score,
            )
        )
        if len(results) >= request.limit:
            break
    return WorkspaceSearchResponse(results=results)
