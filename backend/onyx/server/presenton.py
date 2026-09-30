"""Authenticated presentation workspace and private model relay."""

import asyncio
import json
import os
import time
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

import httpx
import litellm
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field, JsonValue
from sqlalchemy.orm import Session
from starlette.responses import JSONResponse, Response, StreamingResponse

from onyx.auth.permissions import require_permission
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import Permission
from onyx.db.models import User
from onyx.db.presenton import presentation_model
from onyx.db.users import fetch_user_by_id
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.llm.api_surfaces import OPENAI_COMPATIBLE_SURFACES, resolve_api_surface
from onyx.server.presenton_security import (
    issue_token,
    validate_proxy_path,
    verify_token,
)
from onyx.tracing.flows import LLMFlow
from onyx.tracing.llm_utils import traced_llm_call

router = APIRouter(prefix="/orgmesh/presenton")
_sessions: dict[UUID, tuple[float, str]] = {}
_session_lock = asyncio.Lock()
_generation_lock = asyncio.Lock()
BODY_LIMIT = 25 * 1024 * 1024


def _origin() -> str:
    value = os.environ.get("ORGMESH_PRESENTON_URL", "").rstrip("/")
    if not value:
        raise OnyxError(
            OnyxErrorCode.SERVICE_UNAVAILABLE, "Presentation service is not configured"
        )
    return value


def _secret() -> str:
    value = os.environ.get("ORGMESH_PRESENTON_SECRET", "")
    if len(value) < 32:
        raise OnyxError(
            OnyxErrorCode.SERVICE_UNAVAILABLE, "Presentation bridge is not configured"
        )
    return value


async def _cookie(user: User) -> str:
    async with _session_lock:
        cached = _sessions.get(user.id)
        if cached and cached[0] > time.monotonic():
            return cached[1]
        token = issue_token(user.id, "orgmesh-presenton-session", _secret(), 60)
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.post(
                    _origin() + "/api/v1/orgmesh/session", json={"token": token}
                )
                response.raise_for_status()
                data = response.json()
                cookie = f"{data['cookie_name']}={data['token']}"
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise OnyxError(
                OnyxErrorCode.SERVICE_UNAVAILABLE,
                "Presentation service is starting or unavailable",
            ) from exc
        # Prune expired sessions to bound memory.
        expired = [
            owner
            for owner, cached in _sessions.items()
            if cached[0] <= time.monotonic()
        ]
        for owner in expired:
            _sessions.pop(owner, None)
        _sessions[user.id] = (time.monotonic() + 120, cookie)
        return cookie


async def _json(
    user: User, method: str, path: str, payload: dict[str, JsonValue] | None = None
) -> JsonValue:
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.request(
                method,
                _origin() + path,
                headers={"Cookie": await _cookie(user)},
                json=payload,
            )
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as exc:
        raise OnyxError(
            OnyxErrorCode.BAD_GATEWAY,
            "Presentation request failed",
            status_code_override=exc.response.status_code,
        ) from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise OnyxError(
            OnyxErrorCode.SERVICE_UNAVAILABLE, "Presentation service is unavailable"
        ) from exc


def _normalize_dates(value: JsonValue) -> JsonValue:
    if isinstance(value, list):
        return [_normalize_dates(item) for item in value]
    if isinstance(value, dict):
        result: dict[str, JsonValue] = dict(value)
        for key in ("created_at", "updated_at"):
            timestamp = result.get(key)
            if isinstance(timestamp, str):
                parsed = datetime.fromisoformat(timestamp)
                if parsed.tzinfo is None:
                    result[key] = parsed.replace(tzinfo=timezone.utc).isoformat()
        return result
    return value


class PresentationStatus(BaseModel):
    available: bool
    model_name: str | None = None
    provider: str | None = None
    image_generation: bool = False


@router.get("/status")
async def status(
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> PresentationStatus:
    try:
        name, provider = presentation_model(db_session, user)
        await _cookie(user)
        return PresentationStatus(
            available=True, model_name=name, provider=provider.name
        )
    except OnyxError:
        return PresentationStatus(available=False)


@router.get("/presentations")
async def presentations(
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
) -> JsonValue:
    return _normalize_dates(
        await _json(user, "GET", "/api/v1/ppt/presentation/all?include_slides=false")
    )


@router.get("/jobs")
async def jobs(
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
) -> JsonValue:
    return _normalize_dates(
        await _json(
            user, "GET", "/api/v1/async-tasks?type=presentation.generate&limit=50"
        )
    )


class GeneratePresentation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: str = Field(min_length=3, max_length=20000)
    n_slides: int = Field(default=6, ge=3, le=20)
    language: Literal["Chinese", "English"] = "Chinese"
    template: Literal["general"] = "general"
    files: list[str] = Field(default_factory=list, max_length=5)


class GenerationJob(BaseModel):
    task_id: str


@router.post("/generate")
async def generate(
    body: GeneratePresentation,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> GenerationJob:
    presentation_model(db_session, user)
    for path in body.files:
        if (
            not path.startswith(f"/tmp/presenton/{user.id}/")  # noqa: S108 — upstream owner-scoped upload root
            or ".." in path.split("/")
            or "\\" in path
        ):
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT, "Upload reference files before generating"
            )
    async with _generation_lock:
        current = await jobs(user)
        if (
            isinstance(current, list)
            and sum(
                isinstance(job, dict) and job.get("status") == "pending"
                for job in current
            )
            >= 2
        ):
            raise OnyxError(
                OnyxErrorCode.RATE_LIMITED,
                "Wait for an existing presentation to finish",
            )
        payload: dict[str, JsonValue] = {
            **body.model_dump(),
            "web_search": False,
            "export_as": "pptx",
            "trigger_webhook": False,
        }
        result = await _json(
            user, "POST", "/api/v1/ppt/presentation/generate/async", payload
        )
        if not isinstance(result, dict) or not isinstance(result.get("id"), str):
            raise OnyxError(
                OnyxErrorCode.BAD_GATEWAY, "Presentation task was not created"
            )
        return GenerationJob(task_id=result["id"])


async def _request_body(request: Request, limit: int) -> bytes:
    chunks: list[bytes] = []
    length = 0
    async for chunk in request.stream():
        length += len(chunk)
        if length > limit:
            raise OnyxError(OnyxErrorCode.PAYLOAD_TOO_LARGE)
        chunks.append(chunk)
    return b"".join(chunks)


@router.api_route(
    "/proxy/{path:path}", methods=["GET", "POST", "PATCH", "PUT", "DELETE", "HEAD"]
)
async def proxy(
    path: str,
    request: Request,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
) -> Response:
    try:
        validate_proxy_path(path, request.method)
    except ValueError as exc:
        raise OnyxError(
            OnyxErrorCode.UNAUTHORIZED, "Route is unavailable in embedded mode"
        ) from exc
    headers = {
        name: value
        for name, value in request.headers.items()
        if name.lower()
        in {
            "accept",
            "accept-language",
            "content-type",
            "range",
            "if-none-match",
            "if-modified-since",
            "rsc",
            "next-router-state-tree",
            "next-router-prefetch",
            "next-url",
        }
    }
    headers["cookie"] = await _cookie(user)
    headers["accept-encoding"] = "identity"
    # API and private assets go through the original nginx ownership checks.
    upstream_path = (
        "/" + path
        if path.startswith(("api/v1/", "api/v2/", "static/", "app_data/"))
        else "/presenton/" + path
    )
    body = await _request_body(request, BODY_LIMIT)
    client = httpx.AsyncClient(
        timeout=httpx.Timeout(600, connect=15), follow_redirects=False
    )
    try:
        outgoing = client.build_request(
            request.method,
            _origin() + upstream_path,
            params=request.query_params,
            headers=headers,
            content=body,
        )
        upstream = await client.send(outgoing, stream=True)
    except httpx.HTTPError as exc:
        await client.aclose()
        raise OnyxError(
            OnyxErrorCode.SERVICE_UNAVAILABLE, "Presentation service is unavailable"
        ) from exc
    forwarded = {
        name: value
        for name, value in upstream.headers.items()
        if name.lower()
        in {
            "content-type",
            "content-disposition",
            "etag",
            "last-modified",
            "content-range",
            "accept-ranges",
            "content-encoding",
            "content-length",
        }
    }
    forwarded["cache-control"] = "private, no-store"
    if "location" in upstream.headers:
        location = upstream.headers["location"]
        if location.startswith("/presenton/"):
            forwarded["location"] = location
        elif location.startswith("/") and not location.startswith("//"):
            forwarded["location"] = "/presenton" + location
        else:
            await upstream.aclose()
            await client.aclose()
            raise OnyxError(
                OnyxErrorCode.BAD_GATEWAY, "Unexpected presentation redirect"
            )

    async def stream() -> AsyncIterator[bytes]:
        try:
            async for chunk in upstream.aiter_raw():
                yield chunk
        finally:
            await upstream.aclose()
            await client.aclose()

    return StreamingResponse(
        stream(), status_code=upstream.status_code, headers=forwarded
    )


class ChatCompletionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str
    messages: list[dict[str, JsonValue]] = Field(min_length=1, max_length=100)
    stream: bool = False
    max_tokens: int | None = Field(default=None, ge=1, le=16384)
    max_completion_tokens: int | None = Field(default=None, ge=1, le=16384)
    temperature: float | None = Field(default=None, ge=0, le=2)
    top_p: float | None = Field(default=None, ge=0, le=1)
    response_format: dict[str, JsonValue] | None = None
    tools: list[dict[str, JsonValue]] | None = None
    tool_choice: JsonValue = None
    parallel_tool_calls: bool | None = None
    stream_options: dict[str, JsonValue] | None = None
    stop: str | list[str] | None = None
    seed: int | None = None
    frequency_penalty: float | None = None
    presence_penalty: float | None = None
    n: Literal[1] = 1
    user: str | None = None


@router.post("/llm/v1/chat/completions")
async def relay(
    request: Request, db_session: Session = Depends(get_session)
) -> Response:
    authorization = request.headers.get("authorization", "")
    try:
        owner = verify_token(
            authorization.removeprefix("Bearer "), "orgmesh-presenton-llm", _secret()
        )
    except ValueError as exc:
        raise OnyxError(OnyxErrorCode.INVALID_TOKEN) from exc
    user = fetch_user_by_id(db_session, owner)
    if user is None:
        raise OnyxError(OnyxErrorCode.UNAUTHENTICATED)
    name, provider = presentation_model(db_session, user)
    body = ChatCompletionRequest.model_validate_json(
        await _request_body(request, 1024 * 1024)
    )
    kwargs = body.model_dump(
        exclude_none=True, exclude={"model", "user", "max_completion_tokens"}
    )
    kwargs["max_tokens"] = body.max_tokens or body.max_completion_tokens or 8192
    surface = resolve_api_surface(provider.provider, provider.custom_config)
    if surface in OPENAI_COMPATIBLE_SURFACES:
        model = name
        kwargs["custom_llm_provider"] = "openai"
    else:
        model = f"{provider.provider}/{provider.deployment_name or name}"
    # DeepSeek supports JSON object mode. Keep the schema in the prompt.
    if (
        provider.api_base
        and "api.deepseek.com" in provider.api_base
        and body.response_format
        and body.response_format.get("type") == "json_schema"
    ):
        kwargs["response_format"] = {"type": "json_object"}
        kwargs["messages"] = [
            *body.messages,
            {
                "role": "system",
                "content": "Return valid JSON matching this schema: "
                + json.dumps(
                    body.response_format.get("json_schema"), ensure_ascii=False
                ),
            },
        ]
    kwargs.update(
        api_key=provider.api_key, api_base=provider.api_base, timeout=180, num_retries=1
    )
    if provider.api_version:
        kwargs["api_version"] = provider.api_version

    async def response_stream() -> AsyncIterator[bytes]:
        with traced_llm_call(
            flow=LLMFlow.PRESENTATION_GENERATION,
            model=name,
            provider=provider.provider,
            input_messages=body.messages,
            tools=body.tools,
        ):
            try:
                result = await litellm.acompletion(model=model, **kwargs)
                async for chunk in result:
                    yield (
                        "data: " + chunk.model_dump_json(exclude_none=True) + "\n\n"
                    ).encode()
                yield b"data: [DONE]\n\n"
            except Exception:
                yield b'data: {"error":{"message":"Platform model request failed","type":"provider_error"}}\n\n'
                yield b"data: [DONE]\n\n"

    if body.stream:
        return StreamingResponse(response_stream(), media_type="text/event-stream")
    try:
        with traced_llm_call(
            flow=LLMFlow.PRESENTATION_GENERATION,
            model=name,
            provider=provider.provider,
            input_messages=body.messages,
            tools=body.tools,
        ):
            result = await litellm.acompletion(model=model, **kwargs)
            return JSONResponse(result.model_dump(exclude_none=True))
    except Exception as exc:
        raise OnyxError(
            OnyxErrorCode.LLM_PROVIDER_ERROR, "Platform model request failed"
        ) from exc
