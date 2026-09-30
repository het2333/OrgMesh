from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Select
from sqlalchemy.orm import Session

from onyx.access import access
from onyx.configs.constants import MessageType
from onyx.db import chat, chat_search, orgmesh
from onyx.db.models import (
    ChatMessage,
    ChatMessage__SearchDoc,
    ChatSession,
    SearchDoc,
    User,
)
from onyx.error_handling.exceptions import OnyxError


def make_session(user_id: UUID, title: str) -> ChatSession:
    return ChatSession(
        id=uuid4(),
        user_id=user_id,
        description=title,
        time_created=datetime.now(timezone.utc),
        time_updated=datetime.now(timezone.utc),
        deleted=False,
        onyxbot_flow=False,
    )


@pytest.fixture
def reader() -> User:
    return User(id=uuid4(), email="employee@example.com", prior_emails=[])


def test_revoked_conversation_cannot_be_seeded(
    reader: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = make_session(reader.id, "Confidential acquisition")
    db_session = MagicMock(spec=Session)
    db_session.execute.return_value.scalar_one_or_none.return_value = source
    db_session.get.return_value = reader
    monkeypatch.setattr(
        orgmesh, "get_protected_chat_document_ids", lambda *_: ["feishu:doc:private"]
    )
    monkeypatch.setattr(access, "filter_authorized_document_ids", lambda *_: set())
    monkeypatch.setattr(chat, "get_best_persona_id_for_user", lambda **_: None)

    with pytest.raises(OnyxError):
        chat.duplicate_chat_session_for_user_from_slack(db_session, reader, source.id)


def test_copy_rechecks_access_after_target_creation(
    reader: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = make_session(reader.id, "Confidential acquisition")
    target = make_session(reader.id, "Copy")
    db_session = MagicMock(spec=Session)
    db_session.get.side_effect = lambda model, key: (
        reader if model is User else source if key == source.id else target
    )
    monkeypatch.setattr(
        orgmesh, "get_protected_chat_document_ids", lambda *_: ["feishu:doc:private"]
    )
    monkeypatch.setattr(access, "filter_authorized_document_ids", lambda *_: set())

    with pytest.raises(OnyxError):
        chat.add_chats_to_session_from_slack_thread(db_session, source.id, target.id)


def test_native_conversation_remains_readable_without_directory_membership(
    reader: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    native = make_session(reader.id, "Native conversation")
    db_session = MagicMock(spec=Session)
    db_session.execute.return_value.scalar_one_or_none.return_value = native
    monkeypatch.setattr(orgmesh, "get_protected_chat_document_ids", lambda *_: [])

    assert chat.get_chat_session_by_id(native.id, reader.id, db_session) is native


def test_copy_retains_citations_and_tool_only_source_provenance(
    reader: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = make_session(reader.id, "Original")
    target = make_session(reader.id, "Copy")
    cited_doc = SearchDoc(
        id=31,
        document_id="feishu:doc:cited",
        chunk_ind=0,
        semantic_id="Cited document",
        blurb="Private excerpt",
        source_type="feishu",
        boost=0,
        hidden=False,
        score=1,
        match_highlights=[],
        is_internet=False,
        doc_metadata={},
    )
    tool_doc = SearchDoc(
        id=32,
        document_id="feishu:doc:tool-only",
        chunk_ind=0,
        semantic_id="Tool-only document",
        blurb="Private tool excerpt",
        source_type="feishu",
        boost=0,
        hidden=False,
        score=1,
        match_highlights=[],
        is_internet=False,
        doc_metadata={},
    )
    message = ChatMessage(
        id=21,
        chat_session_id=source.id,
        message="The answer [1]",
        token_count=8,
        message_type=MessageType.ASSISTANT,
        citations={1: 31},
        search_docs=[cited_doc],
    )
    root = ChatMessage(
        id=50, chat_session_id=target.id, message_type=MessageType.SYSTEM
    )
    db_session = MagicMock(spec=Session)
    db_session.get.side_effect = lambda model, key: (
        reader if model is User else source if key == source.id else target
    )
    db_session.scalars.return_value.all.return_value = [tool_doc]
    db_session.execute.return_value.scalars.return_value.all.return_value = [message]
    db_session.execute.return_value.scalar_one_or_none.return_value = source
    monkeypatch.setattr(orgmesh, "get_protected_chat_document_ids", lambda *_: [])
    monkeypatch.setattr(chat, "get_or_create_root_message", lambda **_: root)
    added: list[object] = []

    def add(obj: object) -> None:
        if isinstance(obj, (ChatMessage, SearchDoc)):
            obj.id = len(added) + 100
        added.append(obj)

    db_session.add.side_effect = add
    chat.add_chats_to_session_from_slack_thread(db_session, source.id, target.id)

    copied_messages = [obj for obj in added if isinstance(obj, ChatMessage)]
    copied_docs = [obj for obj in added if isinstance(obj, SearchDoc)]
    assert {doc.document_id for doc in copied_docs} == {
        "feishu:doc:cited",
        "feishu:doc:tool-only",
    }
    copied_cited_doc = next(
        doc for doc in copied_docs if doc.document_id == "feishu:doc:cited"
    )
    assert copied_messages[0].citations == {1: copied_cited_doc.id}
    associations = [obj for obj in added if isinstance(obj, ChatMessage__SearchDoc)]
    assert {row.search_doc_id for row in associations} == {
        doc.id for doc in copied_docs
    }


@pytest.mark.parametrize("search", [False, True])
def test_visible_pagination_excludes_revoked_titles(
    reader: User, monkeypatch: pytest.MonkeyPatch, search: bool
) -> None:
    secret = make_session(reader.id, "Confidential acquisition")
    native_one = make_session(reader.id, "Native one")
    native_two = make_session(reader.id, "Native two")
    native_three = make_session(reader.id, "Native three")
    sessions = [secret, native_one, native_two, native_three]
    db_session = MagicMock(spec=Session)
    db_session.get.return_value = reader

    def execute(stmt: Select[Any]) -> MagicMock:
        result = MagicMock()
        if stmt.column_descriptions[0]["entity"] is ChatSession:
            start = stmt._offset_clause.value if stmt._offset_clause is not None else 0
            stop = (
                start + stmt._limit_clause.value
                if stmt._limit_clause is not None
                else None
            )
            result.scalars.return_value.all.return_value = sessions[start:stop]
        else:
            result.all.return_value = [(secret.id, "feishu:doc:private")]
        return result

    db_session.execute.side_effect = execute
    monkeypatch.setattr(access, "filter_authorized_document_ids", lambda *_: set())
    if search:
        result, has_more = chat_search.search_chat_sessions(
            reader.id, db_session, query="acquisition", page=2, page_size=1
        )
        assert [session.description for session in result] == ["Native two"]
        assert has_more
    else:
        result = chat.get_chat_sessions_by_user(
            reader.id, False, db_session, limit=2, include_failed_chats=True
        )
        assert [session.description for session in result] == [
            "Native one",
            "Native two",
        ]
