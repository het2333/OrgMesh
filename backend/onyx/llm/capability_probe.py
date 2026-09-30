import json

from onyx.llm.interfaces import LLM
from onyx.llm.models import NamedToolChoice, UserMessage
from onyx.llm.utils import litellm_exception_to_safe_error
from onyx.server.manage.llm.models import LLMCapabilityCheck, LLMCapabilityReport
from onyx.tracing.flows import LLMFlow
from onyx.tracing.llm_utils import llm_generation_span


def probe_llm_capabilities(llm: LLM) -> LLMCapabilityReport:
    """Check returned content and a tool call without executing any tool."""
    prompt = UserMessage(content="Reply with OK.")
    try:
        with llm_generation_span(llm, LLMFlow.MODEL_CAPABILITY_CHECK, [prompt]):
            has_content = False
            for chunk in llm.stream(prompt, max_tokens=64, timeout_override=15):
                has_content = has_content or bool(chunk.choice.delta.content)
        streaming = LLMCapabilityCheck(
            supported=has_content,
            error=None if has_content else "The stream returned no text.",
        )
    except Exception as error:
        streaming = LLMCapabilityCheck(
            supported=False, error=litellm_exception_to_safe_error(error, llm).message
        )

    tools = [
        {
            "type": "function",
            "function": {
                "name": "orgmesh_probe",
                "description": "Return the supplied value.",
                "parameters": {
                    "type": "object",
                    "properties": {"value": {"type": "string"}},
                    "required": ["value"],
                },
            },
        }
    ]
    prompt = UserMessage(content="Call orgmesh_probe with value orgmesh.")
    try:
        with llm_generation_span(llm, LLMFlow.MODEL_CAPABILITY_CHECK, [prompt], tools):
            response = llm.invoke(
                prompt,
                tools=tools,
                tool_choice=NamedToolChoice(name="orgmesh_probe"),
                max_tokens=96,
                timeout_override=15,
            )
        supported = any(
            call.function.name == "orgmesh_probe"
            and json.loads(call.function.arguments or "null") == {"value": "orgmesh"}
            for call in response.choice.message.tool_calls or []
        )
        tool_calling = LLMCapabilityCheck(
            supported=supported,
            error=None
            if supported
            else "The model did not return the requested tool call.",
        )
    except Exception as error:
        tool_calling = LLMCapabilityCheck(
            supported=False, error=litellm_exception_to_safe_error(error, llm).message
        )
    return LLMCapabilityReport(streaming=streaming, tool_calling=tool_calling)
