"""Default knowledge templates must search before answering; changes roll back."""

import unittest
from typing import cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.chat.chat_processing_checker import set_processing_status
from onyx.chat.chat_state import ChatTurnSetup
from onyx.chat.process_message import build_chat_turn
from onyx.db.agent_templates import get_installed_agent_template
from onyx.db.engine.sql_engine import SqlEngine, get_sqlalchemy_engine
from onyx.db.models import User
from onyx.error_handling.exceptions import OnyxError
from onyx.prompts.agents.templates import TEMPLATE_PROMPTS
from onyx.server.query_and_chat.models import (
    ChatSessionCreationRequest,
    SendMessageRequest,
)


class AgentSearchRequirementChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        SqlEngine.init_engine(pool_size=2, max_overflow=2)

    def setUp(self) -> None:
        self.connection = get_sqlalchemy_engine().connect()
        self.transaction = self.connection.begin()
        self.session = Session(
            bind=self.connection, join_transaction_mode="create_savepoint"
        )
        self.user = (
            self.session.scalars(
                select(User).filter_by(email="orgmesh-local@example.com")
            )
            .unique()
            .one()
        )
        persona = get_installed_agent_template("onboarding", self.session)
        assert persona is not None
        self.persona = persona
        assert self.persona.document_sets
        self.persona.system_prompt = TEMPLATE_PROMPTS["onboarding"]
        self.search_tool = next(
            tool for tool in self.persona.tools if tool.in_code_tool_id == "SearchTool"
        )
        self.session.flush()

    def tearDown(self) -> None:
        self.session.close()
        self.transaction.rollback()
        self.connection.close()

    def build(
        self,
        *,
        allowed_tool_ids: list[int] | None = None,
        forced_tool_id: int | None = None,
        deep_research: bool = False,
    ) -> ChatTurnSetup:
        request = SendMessageRequest(
            message="我是刚入职的工程师，请根据入职资料整理清单。",
            chat_session_info=ChatSessionCreationRequest(persona_id=self.persona.id),
            allowed_tool_ids=allowed_tool_ids,
            forced_tool_id=forced_tool_id,
            deep_research=deep_research,
        )
        generator = build_chat_turn(request, self.user, self.session, None)
        while True:
            try:
                next(generator)
            except StopIteration as done:
                setup = cast(ChatTurnSetup, done.value)
                set_processing_status(setup.chat_session_id, setup.cache, False)
                return setup

    def test_default_template_requires_search_before_generation(self) -> None:
        self.assertEqual(self.build().forced_tool_id, self.search_tool.id)

    def test_custom_prompt_keeps_native_tool_selection(self) -> None:
        self.persona.system_prompt = "只整理用户提供的文本，不检索。"
        self.session.flush()
        self.assertIsNone(self.build().forced_tool_id)

    def test_custom_reminder_keeps_native_tool_selection(self) -> None:
        self.persona.task_prompt = "只整理用户本轮提供的文本。"
        self.session.flush()
        self.assertIsNone(self.build().forced_tool_id)

    def test_missing_search_attachment_cannot_be_silently_skipped(self) -> None:
        self.persona.tools = []
        self.session.flush()
        with self.assertRaises(OnyxError):
            self.build()

    def test_unbound_template_does_not_force_global_search(self) -> None:
        self.persona.document_sets = []
        self.session.flush()
        self.assertIsNone(self.build().forced_tool_id)

    def test_disabled_search_cannot_be_silently_skipped(self) -> None:
        self.search_tool.enabled = False
        self.session.flush()
        with self.assertRaises(OnyxError):
            self.build()

    def test_client_cannot_exclude_search_for_default_knowledge_template(self) -> None:
        with self.assertRaises(OnyxError):
            self.build(allowed_tool_ids=[])

    def test_client_cannot_force_another_tool_to_skip_evidence(self) -> None:
        with self.assertRaises(OnyxError):
            self.build(forced_tool_id=999999)

    def test_deep_research_cannot_bypass_template_evidence(self) -> None:
        with self.assertRaises(OnyxError):
            self.build(deep_research=True)


if __name__ == "__main__":
    unittest.main()
