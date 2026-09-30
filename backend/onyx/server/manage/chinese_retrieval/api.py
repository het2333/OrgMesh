from fastapi import APIRouter, Depends

from onyx.auth.permissions import require_permission
from onyx.db.enums import Permission
from onyx.db.models import User
from onyx.server.manage.chinese_retrieval.models import ChineseRetrievalSettings
from onyx.server.manage.chinese_retrieval.store import (
    load_chinese_retrieval_settings,
    store_chinese_retrieval_settings,
)

router = APIRouter(prefix="/manage/admin/chinese-retrieval")


@router.get("")
def get_chinese_retrieval_settings(
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
) -> ChineseRetrievalSettings:
    return load_chinese_retrieval_settings()


@router.put("")
def update_chinese_retrieval_settings(
    settings: ChineseRetrievalSettings,
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
) -> ChineseRetrievalSettings:
    store_chinese_retrieval_settings(settings)
    return settings
