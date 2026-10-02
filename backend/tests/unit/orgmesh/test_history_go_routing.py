"""Reject Go changes to authorized facts and keep one Python snapshot."""

import asyncio
import json
from copy import deepcopy
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from test_history_projection_contract import CASES

from onyx.presentation_history.contract import (
    decode_request,
    decode_response,
    project_history_python,
)
from onyx.presentation_history.routing import (
    read_history_response,
)


def fixture() -> dict:
    return json.loads((CASES / "statuses.json").read_text())


@pytest.mark.parametrize(
    "mutation",
    [
        "add",
        "reorder",
        "task",
        "deck",
        "revoked",
        "status",
        "time",
        "missing",
        "bool",
        "version",
        "request",
        "extra",
        "duplicate",
    ],
)
def test_go_output_cannot_change_authorized_facts(
    monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    case = fixture()
    req = decode_request(json.dumps(case["request"]).encode())
    bad = deepcopy(case["response"])
    first = bad["rows"][0]
    if mutation == "add":
        bad["rows"].append(
            {**first, "platform_task_id": "00000000-0000-0000-0000-000000009999"}
        )
    elif mutation == "reorder":
        bad["rows"].reverse()
    elif mutation == "task":
        first["task_id"] = bad["rows"][1]["task_id"]
    elif mutation == "deck":
        first["presentation_id"] = bad["rows"][2]["presentation_id"]
    elif mutation == "revoked":
        first["source_chat_id"] = bad["rows"][2]["source_chat_id"]
    elif mutation == "status":
        first["status"] = "error"
    elif mutation == "time":
        first["created_at"] = "wrong"
    elif mutation == "missing":
        del first["project_id"]
    elif mutation == "bool":
        first["project_id"] = True
    elif mutation == "version":
        bad["version"] = 2
    elif mutation == "request":
        bad["request_id"] = "00000000-0000-0000-0000-000000009999"
    elif mutation == "extra":
        first["private"] = "extra"
    elif mutation == "duplicate":
        bad["rows"].append(first)

    async def malicious(request):
        bad["request_id"] = (
            str(request.request_id) if mutation != "request" else bad["request_id"]
        )
        return decode_response(json.dumps(bad).encode())

    monkeypatch.setenv("ORGMESH_HISTORY_READ_BACKEND", "go")
    with patch(
        "onyx.presentation_history.routing.project_history_go", side_effect=malicious
    ):
        assert (
            asyncio.run(read_history_response(list(req.facts), req.query))
            == case["response"]["rows"]
        )


def test_timeout_uses_same_facts_without_requery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    req = decode_request(json.dumps(fixture()["request"]).encode())
    monkeypatch.setenv("ORGMESH_HISTORY_READ_BACKEND", "go")
    with patch(
        "onyx.presentation_history.routing.project_history_go",
        AsyncMock(side_effect=httpx.ReadTimeout("private payload must not appear")),
    ) as client:
        assert asyncio.run(
            read_history_response(list(req.facts), req.query)
        ) == project_history_python(req.facts)
        assert client.await_count == 1


@pytest.mark.parametrize(
    "mode,calls",
    [(None, 0), ("python", 0), ("invalid-private-value", 0), ("shadow", 1), ("go", 1)],
)
def test_python_shadow_go_modes(
    monkeypatch: pytest.MonkeyPatch, mode: str | None, calls: int, caplog
) -> None:
    case = fixture()
    req = decode_request(json.dumps(case["request"]).encode())
    if mode is None:
        monkeypatch.delenv("ORGMESH_HISTORY_READ_BACKEND", raising=False)
    else:
        monkeypatch.setenv("ORGMESH_HISTORY_READ_BACKEND", mode)

    async def honest(request):
        case["response"]["request_id"] = str(request.request_id)
        return decode_response(json.dumps(case["response"]).encode())

    with patch(
        "onyx.presentation_history.routing.project_history_go", side_effect=honest
    ) as client:
        assert (
            asyncio.run(read_history_response(list(req.facts), req.query))
            == case["response"]["rows"]
        )
        assert client.call_count == calls
    assert "invalid-private-value" not in caplog.text


@pytest.mark.parametrize(
    "scenario",
    [
        "chunked_large",
        "declared_large",
        "short",
        "invalid_json",
        "duplicate_key",
        "timeout",
        "encoding",
    ],
)
def test_actual_ipc_transport_bounds_and_timeout(
    tmp_path, monkeypatch, scenario: str
) -> None:
    import errno
    import socket

    from onyx.presentation_history.client import project_history_go

    try:
        check = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        check.close()
    except OSError as exc:
        if exc.errno == errno.EPERM:
            pytest.skip(
                "Executor forbids AF_UNIX sockets; run this IPC test on Linux outside this sandbox"
            )
        raise

    req = decode_request(json.dumps(fixture()["request"]).encode())
    path = tmp_path / "history.sock"
    tmp_path.chmod(0o700)
    monkeypatch.setenv("ORGMESH_HISTORY_GO_SOCKET", str(path))

    async def run() -> None:
        async def handle(reader, writer):
            try:
                header = await reader.readuntil(b"\r\n\r\n")
                length = int(
                    next(
                        line.split(b":", 1)[1]
                        for line in header.split(b"\r\n")
                        if line.lower().startswith(b"content-length:")
                    )
                )
                await reader.readexactly(length)
                if scenario == "timeout":
                    await asyncio.sleep(0.65)
                    return
                if scenario == "chunked_large":
                    writer.write(
                        b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n"
                    )
                    chunk = b" " * 65536
                    for _ in range(5):
                        writer.write(b"10000\r\n" + chunk + b"\r\n")
                    writer.write(b"0\r\n\r\n")
                else:
                    body = (
                        b"{}"
                        if scenario != "duplicate_key"
                        else b'{"version":1,"version":1}'
                    )
                    declared = (
                        262145
                        if scenario == "declared_large"
                        else 10
                        if scenario == "short"
                        else len(body)
                    )
                    encoding = (
                        b"Content-Encoding: gzip\r\n" if scenario == "encoding" else b""
                    )
                    writer.write(
                        b"HTTP/1.1 200 OK\r\nContent-Length: "
                        + str(declared).encode()
                        + b"\r\n"
                        + encoding
                        + b"\r\n"
                        + body
                    )
                await writer.drain()
            except (ConnectionError, asyncio.IncompleteReadError):
                pass
            finally:
                writer.close()
                await writer.wait_closed()

        server = await asyncio.start_unix_server(handle, str(path))
        path.chmod(0o600)
        try:
            with pytest.raises((ValueError, httpx.HTTPError, TimeoutError)):
                await project_history_go(req)
        finally:
            server.close()
            await server.wait_closed()

    asyncio.run(run())


def test_client_refuses_unsafe_socket_paths(tmp_path) -> None:
    from onyx.presentation_history.client import validate_socket_path

    tmp_path.chmod(0o700)
    regular = tmp_path / "file"
    regular.write_text("keep")
    link = tmp_path / "link"
    link.symlink_to(tmp_path, target_is_directory=True)
    for value in ["relative.sock", str(regular), str(link / "file")]:
        with pytest.raises(ValueError):
            validate_socket_path(value)


@pytest.mark.parametrize(
    "scenario",
    [
        "chunked_large",
        "declared_large",
        "short",
        "invalid_json",
        "duplicate_key",
        "timeout",
        "encoding",
        "ok",
    ],
)
def test_streaming_client_checks_without_sockets(monkeypatch, scenario: str) -> None:
    case = fixture()
    req = decode_request(json.dumps(case["request"]).encode())
    body = json.dumps(case["response"]).encode() if scenario == "ok" else b"{}"
    if scenario == "duplicate_key":
        body = b'{"version":1,"version":1}'

    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            if scenario == "timeout":
                await asyncio.sleep(0.65)
            if scenario == "chunked_large":
                for _ in range(5):
                    yield b" " * 65536
            else:
                yield body

    def handler(_request):
        headers = {}
        if scenario == "declared_large":
            headers["Content-Length"] = "262145"
        elif scenario == "short":
            headers["Content-Length"] = "10"
        elif scenario == "encoding":
            headers["Content-Encoding"] = "gzip"
        return httpx.Response(200, headers=headers, stream=Stream())

    transport = httpx.MockTransport(handler)
    from onyx.presentation_history import client

    monkeypatch.setattr(
        client, "validate_socket_path", lambda _: "/private/history.sock"
    )
    monkeypatch.setattr(client.httpx, "AsyncHTTPTransport", lambda **_kwargs: transport)
    if scenario == "ok":
        assert (
            asyncio.run(client.project_history_go(req)).rows_json()
            == case["response"]["rows"]
        )
    else:
        with pytest.raises((ValueError, httpx.HTTPError, TimeoutError)):
            asyncio.run(client.project_history_go(req))


def test_route_timeout_reads_sql_and_acl_once(monkeypatch) -> None:
    from datetime import datetime, timezone
    from types import SimpleNamespace
    from uuid import uuid4

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from onyx.db import presentation_history as database
    from onyx.db.models import Base, PresentationRecord, PresentationTask
    from onyx.server import presenton

    monkeypatch.setenv("ORGMESH_PRESENTON_HISTORY_ENABLED", "true")
    monkeypatch.setenv("ORGMESH_HISTORY_READ_BACKEND", "go")
    owner = SimpleNamespace(id=uuid4())
    sql = create_engine("sqlite://")
    Base.metadata.create_all(
        sql, tables=[PresentationTask.__table__, PresentationRecord.__table__]
    )
    with Session(sql) as db:
        now = datetime.now(timezone.utc)
        db.add(
            PresentationTask(
                id=uuid4(),
                user_id=owner.id,
                status="pending",
                project_id=3,
                source_chat_id=uuid4(),
                created_at=now,
                updated_at=now,
            )
        )
        db.commit()
        with (
            patch.object(
                presenton,
                "history_facts_for_owner",
                wraps=database.history_facts_for_owner,
            ) as facts,
            patch.object(database, "visible_source", return_value=(None, None)) as acl,
            patch(
                "onyx.presentation_history.routing.project_history_go",
                AsyncMock(side_effect=httpx.ReadTimeout("timeout")),
            ),
            patch.object(presenton, "_json", AsyncMock()) as engine,
            patch.object(db, "scalars", wraps=db.scalars) as reads,
        ):
            rows = asyncio.run(presenton.history(50, 0, owner, db, None))
            assert len(rows) == 1 and rows[0]["source_chat_id"] is None
            assert facts.call_count == reads.call_count == acl.call_count == 1
            engine.assert_not_called()
    sql.dispose()
