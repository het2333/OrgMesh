import pytest
from pydantic import ValidationError

from onyx.context.search.preprocessing.chinese_query import expand_chinese_query
from onyx.server.manage.chinese_retrieval.models import (
    ChineseRetrievalSettings,
    GlossaryEntry,
)


def test_expansion_preserves_query_and_matches_chinese_terms() -> None:
    settings = ChineseRetrievalSettings(
        glossary=[GlossaryEntry(term="报销", expansions=["费用报销", "expense"])]
    )
    query = "差旅报销怎么申请？"
    assert expand_chinese_query(query, settings) == query + " 费用报销 expense"


@pytest.mark.parametrize("query", ["SLA2", "XSLA", "sla_policy", "pre-SLAs", "éSLA"])
def test_latin_abbreviations_do_not_match_inside_identifiers(query: str) -> None:
    settings = ChineseRetrievalSettings(
        glossary=[GlossaryEntry(term="SLA", expansions=["服务等级协议"])]
    )
    assert expand_chinese_query(query, settings) == query


def test_full_width_and_case_match_without_changing_original_query() -> None:
    settings = ChineseRetrievalSettings(
        glossary=[GlossaryEntry(term="SLA", expansions=["服务等级协议"])]
    )
    query = "客户的ｓｌａ要求"
    assert expand_chinese_query(query, settings) == query + " 服务等级协议"


def test_longer_chinese_term_suppresses_overlapping_shorter_term() -> None:
    settings = ChineseRetrievalSettings(
        glossary=[
            GlossaryEntry(term="报销", expansions=["expense"]),
            GlossaryEntry(term="差旅报销", expansions=["travel expense"]),
        ]
    )
    assert (
        expand_chinese_query("差旅报销流程", settings) == "差旅报销流程 travel expense"
    )


def test_expansion_has_hard_term_and_character_limits() -> None:
    settings = ChineseRetrievalSettings(
        glossary=[
            GlossaryEntry(term=f"词{index}", expansions=["a" * 64 + str(index)])
            for index in range(4)
        ],
        max_expansions=8,
    )
    query = "词0 词1 词2 词3"
    result = expand_chinese_query(query, settings)
    assert result.startswith(query)
    assert len(result) - len(query) <= 256
    assert len(result[len(query) :].split()) == 3


def test_duplicate_expansions_and_existing_terms_are_not_added() -> None:
    settings = ChineseRetrievalSettings(
        glossary=[GlossaryEntry(term="SLA", expansions=["SLA", "协议", "协议"])]
    )
    assert expand_chinese_query("SLA 协议", settings) == "SLA 协议"


def test_disabled_and_oversized_queries_are_unchanged() -> None:
    settings = ChineseRetrievalSettings(
        enabled=False,
        glossary=[GlossaryEntry(term="报销", expansions=["expense"])],
    )
    assert expand_chinese_query("报销", settings) == "报销"
    settings.enabled = True
    query = "报销" * 3000
    assert expand_chinese_query(query, settings) == query


@pytest.mark.parametrize(
    "entry",
    [
        {"term": "  ", "expansions": ["报销"]},
        {"term": "报销", "expansions": ["\x00"]},
        {"term": "报销", "expansions": ["x" * 81]},
    ],
)
def test_glossary_rejects_empty_control_and_oversized_values(
    entry: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        GlossaryEntry.model_validate(entry)


def test_glossary_rejects_duplicate_normalized_terms() -> None:
    with pytest.raises(ValidationError):
        ChineseRetrievalSettings(
            glossary=[
                GlossaryEntry(term="SLA", expansions=["协议"]),
                GlossaryEntry(term="ｓｌａ", expansions=["服务"]),
            ]
        )


def test_keyword_retrieval_uses_expansion_and_preserves_filters() -> None:
    from unittest.mock import MagicMock

    from onyx.context.search.models import ChunkIndexRequest, IndexFilters
    from onyx.context.search.retrieval.search_runner import _keyword_search

    filters = IndexFilters(access_control_list=["user:123"], document_set=["财务"])
    request = ChunkIndexRequest(
        query="SLA",
        keyword_query="SLA 服务等级协议",
        filters=filters,
        limit=5,
    )
    index = MagicMock()
    index.keyword_retrieval.return_value = []
    assert _keyword_search(request, index) == []
    assert index.keyword_retrieval.call_args.kwargs["query"] == "SLA 服务等级协议"
    assert index.keyword_retrieval.call_args.kwargs["filters"] == filters


def test_hybrid_retrieval_keeps_original_query_embedding() -> None:
    from unittest.mock import MagicMock, patch

    from onyx.context.search.models import ChunkIndexRequest, IndexFilters
    from onyx.context.search.retrieval.search_runner import _embed_and_hybrid_search

    request = ChunkIndexRequest(
        query="SLA",
        keyword_query="SLA 服务等级协议",
        filters=IndexFilters(access_control_list=[]),
    )
    index = MagicMock()
    index.hybrid_retrieval.return_value = []
    with patch(
        "onyx.context.search.retrieval.search_runner.get_query_embedding",
        return_value=[0.1],
    ) as embed_query:
        assert _embed_and_hybrid_search(request, index) == []
    assert embed_query.call_args.args[0] == "SLA"
    assert index.hybrid_retrieval.call_args.kwargs["query"] == "SLA"
    assert index.hybrid_retrieval.call_args.kwargs["final_keywords"] == [
        "SLA 服务等级协议"
    ]


def test_expansion_term_count_respects_configured_and_hard_cap() -> None:
    settings = ChineseRetrievalSettings(
        glossary=[
            GlossaryEntry(term=f"术语{index}", expansions=[f"定义{index}"])
            for index in range(10)
        ]
    )
    query = " ".join(entry.term for entry in settings.glossary)
    assert len(expand_chinese_query(query, settings)[len(query) :].split()) == 8
    settings.max_expansions = 2
    assert len(expand_chinese_query(query, settings)[len(query) :].split()) == 2
    with pytest.raises(ValidationError):
        ChineseRetrievalSettings(max_expansions=9)


def test_runtime_expansion_limit_also_bounds_trusted_model_construction() -> None:
    settings = ChineseRetrievalSettings.model_construct(
        enabled=True,
        max_expansions=100,
        glossary=[
            GlossaryEntry(term=f"术语{index}", expansions=[f"定义{index}"])
            for index in range(10)
        ],
    )
    query = " ".join(entry.term for entry in settings.glossary)
    assert len(expand_chinese_query(query, settings)[len(query) :].split()) == 8
