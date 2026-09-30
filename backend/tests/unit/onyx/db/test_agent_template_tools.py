from unittest.mock import MagicMock, patch

from sqlalchemy.orm import Session

from onyx.db.agent_templates import get_agent_template_tool_ids
from onyx.db.models import Tool

TOOLS = [
    Tool(
        id=1,
        name="search",
        display_name="Search",
        in_code_tool_id="SearchTool",
        enabled=True,
    ),
    Tool(
        id=9,
        name="read_file",
        display_name="Read File",
        in_code_tool_id="FileReaderTool",
        enabled=True,
    ),
]


def test_empty_full_workspace_does_not_attach_unavailable_tools() -> None:
    with (
        patch("onyx.db.agent_templates.get_tools", return_value=TOOLS),
        patch(
            "onyx.tools.tool_implementations.search.search_tool.SearchTool.is_available",
            return_value=False,
        ),
        patch(
            "onyx.tools.tool_implementations.file_reader.file_reader_tool.FileReaderTool.is_available",
            return_value=False,
        ),
    ):
        assert get_agent_template_tool_ids(MagicMock(spec=Session), True) == []


def test_full_workspace_with_knowledge_attaches_native_search() -> None:
    with (
        patch("onyx.db.agent_templates.get_tools", return_value=TOOLS),
        patch(
            "onyx.tools.tool_implementations.search.search_tool.SearchTool.is_available",
            return_value=True,
        ),
        patch(
            "onyx.tools.tool_implementations.file_reader.file_reader_tool.FileReaderTool.is_available",
            return_value=False,
        ),
    ):
        assert get_agent_template_tool_ids(MagicMock(spec=Session), True) == [1]
