"""Select a read projector on one authorized snapshot; retain Python fallback."""

import logging
import os
from uuid import uuid4

import httpx
from pydantic import JsonValue

from onyx.presentation_history.client import project_history_go
from onyx.presentation_history.contract import (
    HistoryFact,
    HistoryProjectionRequest,
    HistoryProjectionResponse,
    HistoryQuery,
    project_history_python,
)

logger = logging.getLogger(__name__)


def validate_projection_response(
    request: HistoryProjectionRequest, response: HistoryProjectionResponse
) -> list[dict[str, JsonValue]]:
    rows = response.rows_json()
    if response.version != request.version or response.request_id != request.request_id:
        raise ValueError("identity_mismatch")
    if rows != project_history_python(request.facts):
        raise ValueError("projection_mismatch")
    return rows


async def read_history_response(
    facts: list[HistoryFact], query: HistoryQuery
) -> list[dict[str, JsonValue]]:
    python_rows = project_history_python(facts)
    mode = os.environ.get("ORGMESH_HISTORY_READ_BACKEND", "python")
    if mode not in {"python", "shadow", "go"}:
        logger.warning(
            "history_read mode=python outcome=config_fallback reason=invalid_backend"
        )
        mode = "python"
    if mode == "python":
        return python_rows
    request = HistoryProjectionRequest(
        version=1, request_id=uuid4(), query=query, facts=tuple(facts)
    )
    try:
        rows = validate_projection_response(request, await project_history_go(request))
    except (httpx.HTTPError, OSError, ValueError, TimeoutError):
        logger.warning(
            "history_read mode=%s outcome=fallback reason=projector_unavailable", mode
        )
        return python_rows
    logger.debug("history_read mode=%s outcome=matched", mode)
    return rows if mode == "go" else python_rows
