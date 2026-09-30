from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.context.search.models import InferenceChunk
from onyx.db.models import User
from onyx.server import orgmesh


def test_search_without_llm_keeps_source_filters_and_deduplicates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chunks = [
        InferenceChunk(
            document_id=document_id,
            chunk_id=index,
            blurb="中文制度",
            content="必须提交申请",
            source_links={0: "https://example.com/policy"},
            image_file_id=None,
            section_continuation=False,
            source_type=DocumentSource.FILE,
            semantic_identifier="制度文件",
            title="制度文件",
            boost=0,
            score=1.0,
            hidden=False,
            metadata={},
            match_highlights=[],
            doc_summary="",
            chunk_context="",
            updated_at=None,
        )
        for index, document_id in enumerate(["a", "a", "b", "c"])
    ]
    observed = []

    def retrieve(**kwargs):
        observed.append(kwargs)
        return chunks

    monkeypatch.setattr(orgmesh, "get_current_search_settings", lambda _: None)
    monkeypatch.setattr(orgmesh, "get_default_document_index", lambda *_: None)
    monkeypatch.setattr(orgmesh, "search_pipeline", retrieve)
    result = orgmesh.search_workspace(
        orgmesh.WorkspaceSearchRequest(
            query="制度", sources=[DocumentSource.FILE], limit=2, hybrid_alpha=0
        ),
        User(id=uuid4(), email="employee@example.com"),
        MagicMock(spec=Session),
    )
    assert [item.document_id for item in result.results] == ["a", "b"]
    request = observed[0]["chunk_search_request"]
    assert request.user_selected_filters.source_type == [DocumentSource.FILE]
    assert request.hybrid_alpha == 0
    assert not request.bypass_acl
    assert observed[0]["force_configured_document_set_scope"] is True


@pytest.mark.parametrize("query", ["", "   ", "x" * 2049])
def test_search_rejects_empty_or_oversize_queries(query: str) -> None:
    with pytest.raises(ValidationError):
        orgmesh.WorkspaceSearchRequest(query=query)
