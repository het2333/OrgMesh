from collections.abc import Iterator
from unittest.mock import patch

from onyx.llm.capability_probe import probe_llm_capabilities
from onyx.llm.interfaces import LLM, LLMConfig
from onyx.llm.model_response import (
    ChatCompletionMessageToolCall,
    Choice,
    Delta,
    FunctionCall,
    Message,
    ModelResponse,
    ModelResponseStream,
    StreamingChoice,
)


class ProbeLLM(LLM):
    def __init__(
        self,
        content: str,
        tool_name: str | None,
        arguments: str = '{"value":"orgmesh"}',
    ) -> None:
        self.content = content
        self.tool_name = tool_name
        self.arguments = arguments

    @property
    def config(self) -> LLMConfig:
        return LLMConfig(
            model_provider="openai_compatible",
            model_name="test",
            temperature=0,
            max_input_tokens=4096,
            api_key="secret-probe-key",
        )

    def stream(
        self, *_args: object, **_kwargs: object
    ) -> Iterator[ModelResponseStream]:
        yield ModelResponseStream(
            id="s",
            created="0",
            choice=StreamingChoice(delta=Delta(content=self.content)),
        )

    def invoke(self, *_args: object, **_kwargs: object) -> ModelResponse:
        calls = (
            [
                ChatCompletionMessageToolCall(
                    id="t",
                    function=FunctionCall(
                        name=self.tool_name, arguments=self.arguments
                    ),
                )
            ]
            if self.tool_name
            else []
        )
        return ModelResponse(
            id="i", created="0", choice=Choice(message=Message(tool_calls=calls))
        )


def test_probe_does_not_claim_empty_stream_or_missing_tool_is_supported() -> None:
    result = probe_llm_capabilities(ProbeLLM("", None))
    assert not result.streaming.supported
    assert not result.tool_calling.supported


def test_probe_accepts_only_the_requested_tool_and_valid_arguments() -> None:
    result = probe_llm_capabilities(ProbeLLM("OK", "orgmesh_probe"))
    assert result.streaming.supported
    assert result.tool_calling.supported
    assert not probe_llm_capabilities(
        ProbeLLM("OK", "other_tool")
    ).tool_calling.supported
    assert not probe_llm_capabilities(
        ProbeLLM("OK", "orgmesh_probe", '{"value":"wrong"}')
    ).tool_calling.supported
    assert not probe_llm_capabilities(
        ProbeLLM("OK", "orgmesh_probe", "invalid-json")
    ).tool_calling.supported


def test_probe_redacts_upstream_error() -> None:
    with patch.object(ProbeLLM, "stream", side_effect=RuntimeError("secret-probe-key")):
        result = probe_llm_capabilities(ProbeLLM("OK", "orgmesh_probe"))
    assert not result.streaming.supported
    assert "secret-probe-key" not in (result.streaming.error or "")
