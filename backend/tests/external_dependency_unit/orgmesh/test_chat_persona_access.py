"""Chat and attachment access checks in PostgreSQL, with an outer rollback."""

import unittest
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from onyx.access.models import ExternalAccess
from onyx.configs.constants import DocumentSource, MessageType
from onyx.connectors.models import InputType
from onyx.db.chat import (
    add_chats_to_session_from_slack_thread,
    duplicate_chat_session_for_user_from_slack,
    get_chat_messages_by_session,
    get_chat_session_by_id,
    get_chat_sessions_by_user,
    translate_db_message_to_chat_message_detail,
)
from onyx.db.chat_search import search_chat_sessions
from onyx.db.document_access import (
    apply_document_access_filter,
    get_accessible_documents_by_ids,
)
from onyx.db.engine.sql_engine import SqlEngine, get_sqlalchemy_engine
from onyx.db.enums import AccessType, ConnectorCredentialPairStatus
from onyx.db.models import (
    ChatMessage,
    ChatSession,
    ChatSessionSharedStatus,
    Connector,
    ConnectorCredentialPair,
    Credential,
    Document,
    DocumentByConnectorCredentialPair,
    OrgMeshDirectoryUser,
    Persona,
    SearchDoc,
    ToolCall,
    User,
)
from onyx.db.orgmesh import (
    get_protected_chat_document_ids,
    refresh_source_document_access,
)
from onyx.db.persona import filter_persona_snapshot_attachments
from onyx.error_handling.exceptions import OnyxError
from onyx.kg.models import KGStage
from onyx.server.features.persona.models import (
    MinimalPersonaSnapshot,
    PersonaSnapshot,
)


class ChatPersonaAccessChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        SqlEngine.init_engine(pool_size=1, max_overflow=0)

    def setUp(self) -> None:
        self.connection = get_sqlalchemy_engine().connect()
        self.transaction = self.connection.begin()
        self.session = Session(
            bind=self.connection, join_transaction_mode="create_savepoint"
        )
        self.now = datetime.now(timezone.utc)
        self.alice = self.make_user("alice")
        self.bob = self.make_user("bob")
        self.membership = self.make_membership(self.alice, ["engineering"])
        self.make_membership(self.bob, ["sales"])
        self.persona = Persona(
            name=f"Access test {uuid4().hex}",
            description="Synthetic test agent",
            user_id=self.alice.id,
            is_public=True,
        )
        self.connector = Connector(
            name=f"Access test {uuid4().hex}",
            source=DocumentSource.FEISHU,
            input_type=InputType.POLL,
            connector_specific_config={},
        )
        self.credential = Credential(
            source=DocumentSource.FEISHU, credential_json=None, user_id=self.alice.id
        )
        self.session.add_all([self.persona, self.connector, self.credential])
        self.session.flush()
        self.cc_pair = ConnectorCredentialPair(
            connector_id=self.connector.id,
            credential_id=self.credential.id,
            name=f"Access test {uuid4().hex}",
            status=ConnectorCredentialPairStatus.ACTIVE,
            access_type=AccessType.PUBLIC,
            creator_id=self.bob.id,
        )
        self.session.add(self.cc_pair)
        self.session.flush()
        self.document = self.make_document("Synthetic private policy")
        self.tool_document = self.make_document("Synthetic private tool result")
        self.native_document = self.make_document(
            "Synthetic native document", native=True
        )

    def tearDown(self) -> None:
        self.session.close()
        self.transaction.rollback()
        self.connection.close()

    def make_user(self, prefix: str) -> User:
        user = User(
            id=uuid4(),
            email=f"{prefix}-{uuid4().hex}@example.com",
            hashed_password="unused-test-value",
            is_active=True,
            is_verified=True,
            prior_emails=[],
        )
        self.session.add(user)
        self.session.flush()
        return user

    def make_membership(
        self, user: User, departments: list[str]
    ) -> OrgMeshDirectoryUser:
        membership = OrgMeshDirectoryUser(
            email=user.email,
            employee_id=uuid4().hex,
            department_ids=departments,
            active=True,
            expires_at=self.now + timedelta(minutes=15),
            updated_at=self.now,
        )
        self.session.add(membership)
        self.session.flush()
        return membership

    def make_document(self, title: str, native: bool = False) -> Document:
        document = Document(
            id=f"native:{uuid4().hex}" if native else f"feishu:docx:{uuid4().hex}",
            semantic_id=title,
            link="https://example.com/synthetic",
            kg_stage=KGStage.NOT_STARTED,
            is_public=True,
            external_user_emails=None if native else [self.alice.email],
            external_user_group_ids=None if native else [],
            doc_metadata={}
            if native
            else {"orgmesh_acl_checked_at": self.now.timestamp()},
        )
        self.session.add(document)
        self.session.flush()
        self.session.add(
            DocumentByConnectorCredentialPair(
                id=document.id,
                connector_id=self.connector.id,
                credential_id=self.credential.id,
                has_been_indexed=True,
            )
        )
        self.session.flush()
        return document

    def saved_doc(self, document: Document) -> SearchDoc:
        saved = SearchDoc(
            document_id=document.id,
            chunk_ind=0,
            semantic_id=document.semantic_id,
            link=document.link,
            blurb="Synthetic confidential excerpt",
            source_type=DocumentSource.FEISHU,
            boost=0,
            hidden=False,
            doc_metadata={},
            score=1,
            match_highlights=[],
        )
        self.session.add(saved)
        self.session.flush()
        return saved

    def make_chat(
        self, title: str, protected: bool = True, age: int = 0, slack: bool = False
    ) -> tuple[ChatSession, ChatMessage]:
        chat = ChatSession(
            id=uuid4(),
            user_id=self.alice.id,
            persona_id=self.persona.id,
            description=title,
            time_created=self.now - timedelta(seconds=age),
            time_updated=self.now - timedelta(seconds=age),
            shared_status=ChatSessionSharedStatus.PUBLIC,
            onyxbot_flow=slack,
            slack_thread_id=f"test-{uuid4().hex}" if slack else None,
        )
        self.session.add(chat)
        self.session.flush()
        root = ChatMessage(
            chat_session_id=chat.id,
            message="",
            token_count=0,
            message_type=MessageType.SYSTEM,
        )
        self.session.add(root)
        self.session.flush()
        message = ChatMessage(
            chat_session_id=chat.id,
            parent_message_id=root.id,
            message="needle synthetic answer [1]",
            token_count=8,
            message_type=MessageType.ASSISTANT,
        )
        if protected:
            saved = self.saved_doc(self.document)
            message.search_docs = [saved]
            message.citations = {1: saved.id}
        self.session.add(message)
        self.session.flush()
        root.latest_child_message_id = message.id
        self.session.flush()
        return chat, message

    def revoke(self, document: Document) -> None:
        refresh_source_document_access(
            self.session,
            {document.id: (ExternalAccess.empty(), self.now.timestamp() + 1)},
        )

    def sql_visible(self, user: User | None) -> set[str]:
        stmt = select(Document).where(
            Document.id.in_([self.document.id, self.native_document.id])
        )
        stmt = apply_document_access_filter(
            stmt, user.email if user else None, [], user_id=user.id if user else None
        )
        return {document.id for document in self.session.scalars(stmt).all()}

    def test_cached_and_shared_history_recheck_source_revocation(self) -> None:
        chat, message = self.make_chat("Synthetic confidential title")
        self.document.external_user_emails = [self.alice.email, self.bob.email]
        self.session.flush()
        self.assertEqual(
            get_chat_session_by_id(chat.id, self.alice.id, self.session).id, chat.id
        )
        self.assertEqual(
            get_chat_session_by_id(
                chat.id, self.bob.id, self.session, is_shared=True
            ).id,
            chat.id,
        )
        self.assertTrue(translate_db_message_to_chat_message_detail(message).citations)
        self.revoke(self.document)
        self.session.expire_all()
        for reader in (self.alice.id, self.bob.id, None):
            with self.subTest(reader=reader), self.assertRaises(OnyxError):
                get_chat_session_by_id(chat.id, reader, self.session, is_shared=True)
        with self.assertRaises(OnyxError):
            get_chat_messages_by_session(chat.id, self.alice.id, self.session)

    def test_history_denies_stale_source_and_directory_but_keeps_native_chat(
        self,
    ) -> None:
        chat, _ = self.make_chat("Synthetic confidential title")
        native, _ = self.make_chat("Native title", protected=False)
        self.document.doc_metadata = {
            "orgmesh_acl_checked_at": (self.now - timedelta(minutes=16)).timestamp()
        }
        self.session.flush()
        with self.assertRaises(OnyxError):
            get_chat_session_by_id(chat.id, self.alice.id, self.session)
        self.document.doc_metadata = {"orgmesh_acl_checked_at": self.now.timestamp()}
        self.membership.expires_at = self.now - timedelta(seconds=1)
        self.session.flush()
        with self.assertRaises(OnyxError):
            get_chat_session_by_id(chat.id, self.alice.id, self.session)
        self.assertEqual(
            get_chat_session_by_id(native.id, self.alice.id, self.session).id, native.id
        )

    def test_history_and_search_count_only_visible_pagination_rows(self) -> None:
        for index in range(102):
            self.make_chat(f"needle private title {index}", age=index)
        native = [
            self.make_chat(
                f"needle native title {index}", protected=False, age=200 + index
            )[0]
            for index in range(3)
        ]
        self.revoke(self.document)
        for include_failed in (False, True):
            with self.subTest(include_failed=include_failed):
                listed = get_chat_sessions_by_user(
                    self.alice.id,
                    False,
                    self.session,
                    limit=2,
                    include_failed_chats=include_failed,
                )
                self.assertEqual(
                    [chat.id for chat in listed], [chat.id for chat in native[:2]]
                )
        for query in (None, "needle"):
            with self.subTest(query=query):
                first, has_more = search_chat_sessions(
                    self.alice.id, self.session, query=query, page=1, page_size=1
                )
                second, _ = search_chat_sessions(
                    self.alice.id, self.session, query=query, page=2, page_size=1
                )
                self.assertEqual([chat.id for chat in first], [native[0].id])
                self.assertTrue(has_more)
                self.assertEqual([chat.id for chat in second], [native[1].id])

    def test_slack_copy_preserves_citations_and_tool_only_revocation(self) -> None:
        source, original_message = self.make_chat("needle Slack answer", slack=True)
        tool = ToolCall(
            chat_session_id=source.id,
            parent_chat_message_id=original_message.id,
            turn_number=0,
            tool_id=0,
            tool_call_id=uuid4().hex,
            tool_call_arguments={},
            tool_call_response="Synthetic tool result",
            tool_call_tokens=3,
            search_docs=[self.saved_doc(self.tool_document)],
        )
        self.session.add(tool)
        self.session.flush()
        original_doc_ids = {doc.id for doc in original_message.search_docs} | {
            doc.id for doc in tool.search_docs
        }
        target = duplicate_chat_session_for_user_from_slack(
            self.session, self.alice, source.id
        )
        add_chats_to_session_from_slack_thread(self.session, source.id, target.id)
        self.session.expire_all()
        copied = get_chat_messages_by_session(target.id, self.alice.id, self.session)
        copied_answer = next(
            message
            for message in copied
            if message.message_type == MessageType.ASSISTANT
        )
        self.assertEqual(copied_answer.message, "needle synthetic answer [1]")
        self.assertEqual(
            translate_db_message_to_chat_message_detail(copied_answer).citations,
            {1: self.document.id},
        )
        self.assertTrue(
            original_doc_ids.isdisjoint(
                {doc.id for message in copied for doc in message.search_docs}
            )
        )
        self.assertEqual(
            set(get_protected_chat_document_ids(self.session, target.id)),
            {self.document.id, self.tool_document.id},
        )
        self.revoke(self.tool_document)
        self.session.expire_all()
        with self.assertRaises(OnyxError):
            get_chat_session_by_id(target.id, self.alice.id, self.session)
        with self.assertRaises(OnyxError):
            duplicate_chat_session_for_user_from_slack(
                self.session, self.alice, source.id
            )
        count_before = self.session.scalar(
            select(func.count())
            .select_from(ChatMessage)
            .where(ChatMessage.chat_session_id == target.id)
        )
        with self.assertRaises(OnyxError):
            add_chats_to_session_from_slack_thread(self.session, source.id, target.id)
        count_after = self.session.scalar(
            select(func.count())
            .select_from(ChatMessage)
            .where(ChatMessage.chat_session_id == target.id)
        )
        self.assertEqual(count_after, count_before)

    def test_persona_attachment_sql_overrides_public_connector_and_owner(self) -> None:
        self.assertEqual(
            self.sql_visible(self.alice), {self.document.id, self.native_document.id}
        )
        self.assertEqual(self.sql_visible(self.bob), {self.native_document.id})
        self.assertEqual(self.sql_visible(None), {self.native_document.id})
        allowed = get_accessible_documents_by_ids(
            self.session,
            [self.document.id, self.native_document.id],
            self.bob.email,
            [],
            user_id=self.bob.id,
        )
        self.assertEqual(
            [document.id for document in allowed], [self.native_document.id]
        )

    def test_repeated_copy_retains_tool_only_source_provenance(self) -> None:
        source, message = self.make_chat("needle Slack answer", slack=True)
        self.session.add(
            ToolCall(
                chat_session_id=source.id,
                parent_chat_message_id=message.id,
                turn_number=0,
                tool_id=0,
                tool_call_id=uuid4().hex,
                tool_call_arguments={},
                tool_call_response="Synthetic tool result",
                tool_call_tokens=3,
                search_docs=[self.saved_doc(self.tool_document)],
            )
        )
        self.session.flush()
        first = duplicate_chat_session_for_user_from_slack(
            self.session, self.alice, source.id
        )
        add_chats_to_session_from_slack_thread(self.session, source.id, first.id)
        second = duplicate_chat_session_for_user_from_slack(
            self.session, self.alice, first.id
        )
        add_chats_to_session_from_slack_thread(self.session, first.id, second.id)
        self.assertEqual(
            set(get_protected_chat_document_ids(self.session, second.id)),
            {self.document.id, self.tool_document.id},
        )
        self.revoke(self.tool_document)
        with self.assertRaises(OnyxError):
            get_chat_session_by_id(second.id, self.alice.id, self.session)

    def test_persona_department_acl_and_inactive_membership(self) -> None:
        self.document.external_user_emails = []
        self.document.external_user_group_ids = ["feishu:department:engineering"]
        self.session.flush()
        self.assertIn(self.document.id, self.sql_visible(self.alice))
        self.assertNotIn(self.document.id, self.sql_visible(self.bob))
        self.membership.active = False
        self.session.flush()
        self.assertEqual(self.sql_visible(self.alice), {self.native_document.id})

    def test_persona_sql_denies_missing_expired_and_malformed_authority(self) -> None:
        for metadata in (
            {},
            {"orgmesh_acl_checked_at": "invalid"},
            {"orgmesh_acl_checked_at": True},
            {"orgmesh_acl_checked_at": (self.now - timedelta(minutes=16)).timestamp()},
        ):
            with self.subTest(metadata=metadata):
                self.document.doc_metadata = metadata
                self.session.flush()
                self.assertEqual(
                    self.sql_visible(self.alice), {self.native_document.id}
                )
        self.document.doc_metadata = {"orgmesh_acl_checked_at": self.now.timestamp()}
        self.membership.expires_at = self.now - timedelta(seconds=1)
        self.session.flush()
        self.assertEqual(self.sql_visible(self.alice), {self.native_document.id})
        self.session.delete(self.membership)
        self.session.flush()
        self.assertEqual(self.sql_visible(self.alice), {self.native_document.id})

    def test_persona_metadata_projection_does_not_change_stored_attachments(
        self,
    ) -> None:
        self.persona.attached_documents = [self.document, self.native_document]
        self.session.flush()
        full = PersonaSnapshot.from_model(self.persona)
        minimal = MinimalPersonaSnapshot.from_model(self.persona)
        filter_persona_snapshot_attachments(
            [full, minimal], [self.persona, self.persona], self.bob, self.session
        )
        self.assertEqual(
            [document.id for document in full.attached_documents],
            [self.native_document.id],
        )
        self.assertEqual(minimal.attached_document_count, 1)
        self.assertEqual(
            {document.id for document in self.persona.attached_documents},
            {self.document.id, self.native_document.id},
        )
        owner = PersonaSnapshot.from_model(self.persona)
        filter_persona_snapshot_attachments(
            [owner], [self.persona], self.alice, self.session
        )
        self.assertEqual(
            {document.id for document in owner.attached_documents},
            {self.document.id, self.native_document.id},
        )
        self.revoke(self.document)
        filtered = PersonaSnapshot.from_model(self.persona)
        filter_persona_snapshot_attachments(
            [filtered], [self.persona], self.alice, self.session
        )
        self.assertEqual(
            [document.id for document in filtered.attached_documents],
            [self.native_document.id],
        )


if __name__ == "__main__":
    unittest.main()
