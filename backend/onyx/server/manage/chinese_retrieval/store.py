from typing import cast

from onyx.key_value_store.factory import get_kv_store
from onyx.key_value_store.interface import KvKeyNotFoundError
from onyx.server.manage.chinese_retrieval.models import ChineseRetrievalSettings
from onyx.utils.special_types import JSON_ro

CHINESE_RETRIEVAL_SETTINGS_KEY = "chinese_retrieval_settings"


def load_chinese_retrieval_settings() -> ChineseRetrievalSettings:
    try:
        value = get_kv_store().load(CHINESE_RETRIEVAL_SETTINGS_KEY)
    except KvKeyNotFoundError:
        return ChineseRetrievalSettings()
    return ChineseRetrievalSettings.model_validate(value)


def store_chinese_retrieval_settings(settings: ChineseRetrievalSettings) -> None:
    validated = ChineseRetrievalSettings.model_validate(settings.model_dump())
    get_kv_store().store(
        CHINESE_RETRIEVAL_SETTINGS_KEY,
        cast(JSON_ro, validated.model_dump(mode="json")),
    )
