"""Synthetic authorized-page benchmark. Never use this as SQL/ACL evidence."""

import argparse
import asyncio
import json
import os
import resource
import statistics
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import UUID, uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from onyx.presentation_history.client import project_history_go  # noqa: E402
from onyx.presentation_history.contract import (  # noqa: E402
    HistoryFact,
    HistoryProjectionRequest,
    HistoryQuery,
    project_history_python,
)
from onyx.presentation_history.routing import validate_projection_response  # noqa: E402


def percentile(values: list[float], fraction: float) -> float:
    return sorted(values)[min(len(values) - 1, int((len(values) - 1) * fraction))]


def rss_kib(pid: int) -> int | None:
    try:
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1])
    except FileNotFoundError:
        pass
    return None


def go_cpu_seconds(pid: int) -> float:
    fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
    return (int(fields[11]) + int(fields[12])) / os.sysconf("SC_CLK_TCK")


def facts_for_size(size: int) -> list[HistoryFact]:
    return [
        HistoryFact(
            platform_id=UUID(int=i + 1),
            engine_task_id=None,
            deck_id=None,
            state="pending",
            visible_project_id=None,
            visible_source_chat_id=None,
            created_at="2026-10-01T00:00:00+00:00",
            updated_at="2026-10-01T00:00:00",
        )
        for i in range(size)
    ]


async def measure_ipc(
    facts: list[HistoryFact], concurrency: int, samples: int, pid: int
) -> dict:
    req = HistoryProjectionRequest(
        version=1,
        request_id=uuid4(),
        query=HistoryQuery(limit=len(facts), offset=0, status=None),
        facts=tuple(facts),
    )
    semaphore = asyncio.Semaphore(concurrency)

    async def sample() -> float:
        async with semaphore:
            start = time.perf_counter_ns()
            result = await project_history_go(req)
            validate_projection_response(req, result)
            return (time.perf_counter_ns() - start) / 1000

    start = time.perf_counter()
    cpu = time.process_time()
    go_cpu = go_cpu_seconds(pid)
    values = await asyncio.gather(*(sample() for _ in range(samples)))
    return {
        "p50_us": statistics.median(values),
        "p95_us": percentile(values, 0.95),
        "wall_seconds": time.perf_counter() - start,
        "python_cpu_seconds": time.process_time() - cpu,
        "go_cpu_seconds": go_cpu_seconds(pid) - go_cpu,
        "python_rss_kib": rss_kib(os.getpid()),
        "go_rss_kib": rss_kib(pid),
        "total_rss_kib": (rss_kib(os.getpid()) or 0) + (rss_kib(pid) or 0),
    }


def run(samples: int, binary: Path | None) -> dict:
    results = []
    process = None
    directory = None
    try:
        if binary is not None:
            directory = tempfile.TemporaryDirectory(prefix="history-bench-")
            socket = Path(directory.name) / "history.sock"
            process = subprocess.Popen(
                [
                    str(binary.resolve()),
                    "--socket",
                    str(socket),
                    "--peer-uid",
                    str(os.geteuid()),
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            for _ in range(200):
                if socket.exists():
                    break
                if process.poll() is not None:
                    raise RuntimeError(
                        "Go daemon could not create its Unix socket; IPC benchmark unavailable"
                    )
                time.sleep(0.01)
            if not socket.exists():
                raise RuntimeError("Go daemon readiness timeout")
            os.environ["ORGMESH_HISTORY_GO_SOCKET"] = str(socket)
        for history_size in (100, 1000, 10000):
            dataset = facts_for_size(history_size)
            for page_size in (21, 100):
                page = dataset[:page_size]
                for concurrency in (1, 10, 50):

                    def sample(_: int, page: list[HistoryFact] = page) -> float:
                        start = time.perf_counter_ns()
                        project_history_python(page)
                        return (time.perf_counter_ns() - start) / 1000

                    for _ in range(100):
                        sample(0)
                    start = time.perf_counter()
                    cpu = time.process_time()
                    with ThreadPoolExecutor(max_workers=concurrency) as executor:
                        values = list(executor.map(sample, range(samples)))
                    result = {
                        "history_size": history_size,
                        "page_size": page_size,
                        "concurrency": concurrency,
                        "samples": samples,
                        "python_projection": {
                            "p50_us": statistics.median(values),
                            "p95_us": percentile(values, 0.95),
                            "wall_seconds": time.perf_counter() - start,
                            "python_cpu_seconds": time.process_time() - cpu,
                            "python_rss_kib": rss_kib(os.getpid()),
                            "python_peak_rss_kib": resource.getrusage(
                                resource.RUSAGE_SELF
                            ).ru_maxrss,
                        },
                    }
                    if process is not None:
                        result["go_ipc_with_python_validation"] = asyncio.run(
                            measure_ipc(page, concurrency, samples, process.pid)
                        )
                    else:
                        result["go_ipc_with_python_validation"] = None
                    results.append(result)
        return {
            "kind": "synthetic authorized facts only",
            "environment": {
                "python": sys.version.split()[0],
                "platform": sys.platform,
                "cpu_count": os.cpu_count(),
            },
            "notes": [
                "History sizes affect only synthetic setup. No SQL, tenant middleware, live ACL, or engine was measured.",
                "Thread concurrency measures local Python scheduling; it does not model live API requests.",
                "Python projection timing excludes queue delay; IPC timing includes the client and Python response validation.",
                "RSS is sampled at case completion. Peak RSS is process-wide and cumulative.",
                "Missing IPC/Go RSS means unmeasured, never zero. No product speed claim is supported.",
            ],
            "results": results,
        }
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            process.wait(timeout=3)
        if directory is not None:
            directory.cleanup()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", type=int, default=1000)
    parser.add_argument("--binary", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not 100 <= args.samples <= 10000:
        parser.error("samples must be 100..10000")
    output = json.dumps(run(args.samples, args.binary), indent=2) + "\n"
    if args.output:
        args.output.write_text(output)
    else:
        print(output)
