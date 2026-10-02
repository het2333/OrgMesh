"""Run real Python/Go IPC without application, database, or engine credentials."""

import argparse
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from onyx.presentation_history.client import project_history_go  # noqa: E402
from onyx.presentation_history.contract import (  # noqa: E402
    decode_request,
    project_history_python,
)
from onyx.presentation_history.routing import (  # noqa: E402
    read_history_response,
    validate_projection_response,
)


async def run(binary: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="orgmesh-ipc-") as directory:
        socket = Path(directory) / "history.sock"
        process = await asyncio.create_subprocess_exec(
            str(binary),
            "--socket",
            str(socket),
            "--peer-uid",
            str(os.geteuid()),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            for _ in range(200):
                if socket.exists():
                    break
                if process.returncode is not None:
                    raise AssertionError("Go daemon failed to start")
                await asyncio.sleep(0.01)
            assert socket.exists(), "Go socket did not appear"
            assert socket.stat().st_mode & 0o777 == 0o600
            os.environ["ORGMESH_HISTORY_GO_SOCKET"] = str(socket)
            for path in (ROOT / "services/orgmesh-core/testdata/history").glob(
                "*.json"
            ):
                fixture = json.loads(path.read_text())
                req = decode_request(json.dumps(fixture["request"]).encode())
                result = await project_history_go(req)
                assert (
                    validate_projection_response(req, result)
                    == fixture["response"]["rows"]
                )
                for mode in ("python", "shadow", "go"):
                    os.environ["ORGMESH_HISTORY_READ_BACKEND"] = mode
                    assert (
                        await read_history_response(list(req.facts), req.query)
                        == fixture["response"]["rows"]
                    )
            process.terminate()
            await asyncio.wait_for(process.wait(), timeout=3)
            assert process.returncode == 0
            for _ in range(100):
                if not socket.exists():
                    break
                await asyncio.sleep(0.01)
            assert not socket.exists(), "Go socket survived shutdown"
            os.environ["ORGMESH_HISTORY_READ_BACKEND"] = "go"
            assert await read_history_response(
                list(req.facts), req.query
            ) == project_history_python(req.facts)
            assert (await process.communicate())[1] == b"", "Go emitted unexpected logs"
        finally:
            if process.returncode is None:
                process.terminate()
                await asyncio.wait_for(process.wait(), timeout=3)
    print(
        "Real Go/Python IPC: golden rows, three modes, unavailable fallback, clean shutdown passed"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=Path, required=True)
    asyncio.run(run(parser.parse_args().binary.resolve()))
