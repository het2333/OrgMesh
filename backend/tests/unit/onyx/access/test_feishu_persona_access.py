"""Prevent source attachment metadata from bypassing current Feishu access."""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.db.document_access import (
    apply_document_access_filter,
    get_accessible_documents_by_ids,
)
from onyx.db.enums import PersonaSharePermission
from onyx.db.models import Document, HierarchyNode, Persona, User, UserFile
from onyx.db.models import SlackChannelConfig as SlackChannelConfigModel
from onyx.db.persona import (
    filter_persona_snapshot_attachments,
    get_minimal_persona_snapshots_for_user,
    get_minimal_persona_snapshots_paginated,
    get_persona_snapshots_for_user,
    get_persona_snapshots_paginated,
    upsert_persona,
)
from onyx.server.features.persona.models import (
    FullPersonaSnapshot,
    MinimalPersonaSnapshot,
    PersonaSnapshot,
)
from onyx.server.manage.models import SlackChannelConfig


def _document(document_id: str, source: DocumentSource) -> Document:
    return Document(
        id=document_id,
        semantic_id=f"Title {document_id}",
        link=f"https://example.com/{document_id}",
        parent_hierarchy_node=HierarchyNode(source=source),
    )


def _persona(persona_id: int, documents: list[Document]) -> Persona:
    return Persona(
        id=persona_id,
        name=f"Shared agent {persona_id}",
        description="Shared agent",
        is_public=True,
        is_listed=True,
        is_featured=False,
        builtin_persona=False,
        deleted=False,
        replace_base_system_prompt=False,
        datetime_aware=True,
        public_permission=PersonaSharePermission.VIEWER,
        attached_documents=documents,
    )


def _user() -> User:
    return User(
        id=uuid4(), email="reader@example.com", is_active=True, is_verified=True
    )


def test_public_sql_candidates_require_source_authorization() -> None:
    native = _document("native-doc", DocumentSource.WEB)
    denied = _document("feishu:private", DocumentSource.FEISHU)
    allowed = _document("feishu:allowed", DocumentSource.FEISHU)
    user = _user()
    session = MagicMock(spec=Session)
    session.get.return_value = user
    session.execute.return_value.scalars.return_value.all.return_value = [
        native,
        denied,
        allowed,
    ]
    with patch(
        "onyx.access.access.filter_authorized_document_ids",
        return_value={native.id, allowed.id},
    ) as authorize:
        documents = get_accessible_documents_by_ids(
            session, [native.id, denied.id, allowed.id], user.email, [], user.id
        )

    assert documents == [native, allowed]
    authorize.assert_called_once_with([native.id, denied.id, allowed.id], user, session)


@pytest.mark.parametrize("has_user_id", [False, True])
def test_missing_user_denies_feishu_candidates(has_user_id: bool) -> None:
    native = _document("native-doc", DocumentSource.WEB)
    private = _document("feishu:private", DocumentSource.FEISHU)
    session = MagicMock(spec=Session)
    session.get.return_value = None
    session.execute.return_value.scalars.return_value.all.return_value = [
        native,
        private,
    ]

    documents = get_accessible_documents_by_ids(
        session,
        [native.id, private.id],
        "reader@example.com",
        [],
        uuid4() if has_user_id else None,
    )

    assert documents == [native]


@pytest.mark.parametrize("snapshot_type", [PersonaSnapshot, FullPersonaSnapshot])
def test_shared_snapshots_filter_revoked_metadata_in_one_batch(
    snapshot_type: type[PersonaSnapshot],
) -> None:
    native = _document("native-doc", DocumentSource.WEB)
    denied = _document("feishu:revoked", DocumentSource.FEISHU)
    allowed = _document("feishu:allowed", DocumentSource.FEISHU)
    personas = [_persona(1, [native, denied]), _persona(2, [denied, allowed])]
    file = UserFile(id=uuid4())
    personas[0].user_files = [file]
    snapshots = [snapshot_type.from_model(persona) for persona in personas]
    user = _user()
    session = MagicMock(spec=Session)

    with patch(
        "onyx.access.access.filter_authorized_document_ids",
        return_value={native.id, allowed.id},
    ) as authorize:
        filter_persona_snapshot_attachments(snapshots, personas, user, session)

    assert [
        [doc.id for doc in snapshot.attached_documents] for snapshot in snapshots
    ] == [
        [native.id],
        [allowed.id],
    ]
    assert snapshots[0].user_file_ids == [str(file.id)]
    assert denied.semantic_id not in snapshots[0].model_dump_json()
    assert denied.link is not None
    assert denied.link not in snapshots[0].model_dump_json()
    assert personas[0].attached_documents == [native, denied]
    assert personas[1].attached_documents == [denied, allowed]
    authorize.assert_called_once()
    assert set(authorize.call_args.args[0]) == {native.id, denied.id, allowed.id}
    session.add.assert_not_called()
    session.commit.assert_not_called()


def test_minimal_counts_and_sources_exclude_revoked_attachment() -> None:
    native = _document("native-doc", DocumentSource.WEB)
    denied = _document("feishu:revoked", DocumentSource.FEISHU)
    persona = _persona(1, [native, denied])
    persona.user_files = [UserFile(id=uuid4())]
    snapshot = MinimalPersonaSnapshot.from_model(persona)
    assert snapshot.attached_document_count == 2
    assert DocumentSource.FEISHU in snapshot.knowledge_sources

    with patch(
        "onyx.access.access.filter_authorized_document_ids", return_value={native.id}
    ):
        filter_persona_snapshot_attachments([snapshot], [persona], _user(), MagicMock())

    assert snapshot.attached_document_count == 1
    assert set(snapshot.knowledge_sources) == {
        DocumentSource.WEB,
        DocumentSource.USER_FILE,
    }
    assert persona.attached_documents == [native, denied]


def test_context_free_snapshots_preserve_native_attachments() -> None:
    native = _document("native-doc", DocumentSource.WEB)
    private = _document("feishu:private", DocumentSource.FEISHU)
    persona = _persona(1, [native, private])
    full = FullPersonaSnapshot.from_model(persona)
    minimal = MinimalPersonaSnapshot.from_model(persona)

    filter_persona_snapshot_attachments(
        [full, minimal], [persona, persona], None, MagicMock()
    )

    assert [doc.id for doc in full.attached_documents] == [native.id]
    assert minimal.attached_document_count == 1
    assert minimal.knowledge_sources == [DocumentSource.WEB]
    assert persona.attached_documents == [native, private]


def test_mixed_attachment_request_rejects_inaccessible_feishu() -> None:
    native = _document("native-doc", DocumentSource.WEB)
    session = MagicMock(spec=Session)
    with (
        patch("onyx.db.persona._get_persona_by_name", return_value=None),
        patch("onyx.db.persona.get_accessible_documents_by_ids", return_value=[native]),
        pytest.raises(ValueError, match="documents not found or not accessible"),
    ):
        upsert_persona(
            user=None,
            name="Shared agent",
            description="Agent",
            starter_messages=None,
            system_prompt=None,
            task_prompt=None,
            datetime_aware=True,
            is_public=True,
            db_session=session,
            document_ids=[native.id, "feishu:private"],
        )

    session.add.assert_not_called()
    session.commit.assert_not_called()


@pytest.mark.parametrize("minimal", [False, True])
@pytest.mark.parametrize("paginated", [False, True])
def test_bulk_reads_apply_attachment_authorization(
    minimal: bool, paginated: bool
) -> None:
    private = _document("feishu:revoked", DocumentSource.FEISHU)
    persona = _persona(1, [private])
    session = MagicMock(spec=Session)
    session.scalars.return_value.all.return_value = [persona]
    with (
        patch("onyx.db.persona._editable_persona_ids_among", return_value=set()),
        patch("onyx.db.persona.get_user_group_ids_for_user", return_value=set()),
        patch("onyx.access.access.filter_authorized_document_ids", return_value=set()),
    ):
        if minimal and paginated:
            snapshots = get_minimal_persona_snapshots_paginated(_user(), session, 0, 10)
        elif minimal:
            snapshots = get_minimal_persona_snapshots_for_user(_user(), session)
        elif paginated:
            snapshots = get_persona_snapshots_paginated(_user(), session, 0, 10)
        else:
            snapshots = get_persona_snapshots_for_user(_user(), session)

    assert private.semantic_id not in snapshots[0].model_dump_json()
    if isinstance(snapshots[0], MinimalPersonaSnapshot):
        assert snapshots[0].attached_document_count == 0
        assert snapshots[0].knowledge_sources == []
    else:
        assert snapshots[0].attached_documents == []
    assert persona.attached_documents == [private]


def test_slack_config_without_reader_omits_feishu_metadata() -> None:
    native = _document("native-doc", DocumentSource.WEB)
    private = _document("feishu:private", DocumentSource.FEISHU)
    persona = _persona(1, [native, private])
    model = SlackChannelConfigModel(
        id=1,
        slack_bot_id=1,
        persona=persona,
        channel_config={"channel_name": "general"},
        enable_auto_filters=False,
        is_default=False,
    )

    config = SlackChannelConfig.from_model(model)

    assert config.persona is not None
    assert [doc.id for doc in config.persona.attached_documents] == [native.id]
    assert private.semantic_id not in config.model_dump_json()
    assert persona.attached_documents == [native, private]


def test_single_persona_response_excludes_revoked_metadata() -> None:
    from onyx.server.features.persona.api import get_persona

    private = _document("feishu:revoked", DocumentSource.FEISHU)
    persona = _persona(1, [private])
    session = MagicMock(spec=Session)
    with (
        patch(
            "onyx.server.features.persona.api.get_persona_by_id", return_value=persona
        ),
        patch(
            "onyx.server.features.persona.api.get_user_group_ids_for_user",
            return_value=set(),
        ),
        patch(
            "onyx.server.features.persona.api.is_persona_editable_by_user",
            return_value=False,
        ),
        patch(
            "onyx.server.features.persona.api.get_active_admin_count", return_value=1
        ),
        patch("onyx.access.access.filter_authorized_document_ids", return_value=set()),
    ):
        snapshot = get_persona(persona.id, _user(), session)

    assert snapshot.attached_documents == []
    assert private.semantic_id not in snapshot.model_dump_json()
    assert persona.attached_documents == [private]
    session.commit.assert_not_called()


def test_sql_guard_restricts_feishu_before_pagination() -> None:
    user = _user()
    statement = apply_document_access_filter(
        select(Document), user.email, [], user.id
    ).limit(10)
    sql = str(
        statement.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    native_branch, feishu_branch = sql.split(" OR document.id LIKE ", 1)

    assert "document.id NOT LIKE 'feishu:%%'" in native_branch
    assert "document.is_public IS true" in native_branch
    assert "document.is_public" not in feishu_branch
    assert "connector_credential_pair.access_type" not in feishu_branch
    assert "jsonb_typeof" in feishu_branch
    assert "AS NUMERIC" in feishu_branch
    assert '"user".is_active IS true' in feishu_branch
    assert '"user".is_verified IS true' in feishu_branch
    assert "\"user\".account_type != 'ANONYMOUS'" in feishu_branch
    assert "orgmesh_directory_user.active IS true" in feishu_branch
    assert "orgmesh_directory_user.expires_at > now()" in feishu_branch
    assert "feishu:department:" in feishu_branch
    assert " - 900" in feishu_branch
    assert " + 60" in feishu_branch
    assert feishu_branch.index(
        "orgmesh_directory_user.expires_at"
    ) < feishu_branch.index("LIMIT 10")


def test_sql_without_user_cannot_return_feishu() -> None:
    statement = apply_document_access_filter(select(Document), "reader@example.com", [])
    sql = str(
        statement.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )

    assert "document.id NOT LIKE 'feishu:%%'" in sql
    assert " OR document.id LIKE " not in sql
