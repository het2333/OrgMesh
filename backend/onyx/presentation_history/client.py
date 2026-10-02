"""Bounded local IPC. No TCP, proxy, retry, database, or engine access."""

import asyncio
import os
import stat
from pathlib import Path

import httpx

from onyx.presentation_history.contract import (
    MAX_BYTES,
    HistoryProjectionRequest,
    HistoryProjectionResponse,
    decode_response,
)

DEFAULT_SOCKET = "/tmp/orgmesh-history-go/history.sock"  # noqa: S108 — validated 0700 directory and 0600 socket
TIMEOUT_SECONDS = 0.5


def validate_socket_path(value: str) -> str:
    path = Path(value)
    if not path.is_absolute() or str(path) != value or ".." in path.parts:
        raise ValueError("unsafe_socket")
    for ancestor in reversed(path.parents):
        if stat.S_ISLNK(ancestor.lstat().st_mode):
            raise ValueError("unsafe_socket")
    parent = path.parent.lstat()
    socket = path.lstat()
    if (
        not stat.S_ISDIR(parent.st_mode)
        or parent.st_uid != os.geteuid()
        or stat.S_IMODE(parent.st_mode) != 0o700
        or not stat.S_ISSOCK(socket.st_mode)
        or socket.st_uid != os.geteuid()
        or stat.S_IMODE(socket.st_mode) != 0o600
    ):
        raise ValueError("unsafe_socket")
    return value


async def project_history_go(
    request: HistoryProjectionRequest,
) -> HistoryProjectionResponse:
    payload = request.model_dump_json().encode()
    if len(payload) > MAX_BYTES:
        raise ValueError("body_bound")
    path = validate_socket_path(
        os.environ.get("ORGMESH_HISTORY_GO_SOCKET", DEFAULT_SOCKET)
    )
    transport = httpx.AsyncHTTPTransport(uds=path, retries=0)
    async with asyncio.timeout(TIMEOUT_SECONDS):
        async with httpx.AsyncClient(
            transport=transport,
            trust_env=False,
            timeout=httpx.Timeout(TIMEOUT_SECONDS),
            follow_redirects=False,
        ) as client:
            async with client.stream(
                "POST",
                "http://history/v1/project-history",
                content=payload,
                headers={
                    "Content-Type": "application/json",
                    "Accept-Encoding": "identity",
                },
            ) as response:
                response.raise_for_status()
                if response.status_code != 200:
                    raise ValueError("invalid_status")
                if response.headers.get("content-encoding", "identity") != "identity":
                    raise ValueError("invalid_encoding")
                declared = response.headers.get("content-length")
                if declared is not None and (
                    not declared.isascii()
                    or not declared.isdecimal()
                    or int(declared) > MAX_BYTES
                ):
                    raise ValueError("body_bound")
                data = bytearray()
                async for chunk in response.aiter_raw(chunk_size=64 * 1024):
                    if len(data) + len(chunk) > MAX_BYTES:
                        raise ValueError("body_bound")
                    data.extend(chunk)
                if declared is not None and len(data) != int(declared):
                    raise ValueError("invalid_length")
                return decode_response(bytes(data))
