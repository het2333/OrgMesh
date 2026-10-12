"""The checker must reject executable dependencies, not matching prose."""

import importlib.util
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[4]


def checker() -> Any:
    path = ROOT / "tools/check_orgmesh_enterprise_boundaries.py"
    assert path.is_file(), "executable enterprise boundary checker is missing"
    spec = importlib.util.spec_from_file_location("enterprise_boundary_checker", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "source",
    [
        "import ee.onyx.main",
        "from ee.onyx import main",
        'import importlib as loader\nloader.import_module("ee.onyx.main")',
        'from importlib import import_module as load\nload("ee.onyx.main")',
        'module = "ee.onyx.main"\n__import__(module)',
        "import importlib\nimportlib.import_module(user_input)",
        'import importlib\nload = importlib.import_module\nload("ee.onyx.main")',
        'load = __import__\nload("ee.onyx.main")',
        'exec("import ee.onyx.main")',
    ],
)
def test_python_executable_enterprise_import_is_rejected(source: str) -> None:
    result = checker().inspect_python(Path("candidate.py"), source)
    assert result["failures"], result


def test_python_prose_is_not_an_executable_enterprise_dependency() -> None:
    result = checker().inspect_python(
        Path("candidate.py"),
        '"""Never call ee.onyx.main."""\nimport httpx\nfrom onyx.db import models',
    )
    assert result["failures"] == []
    assert result["dependencies"] == ["httpx", "onyx.db"]


@pytest.mark.parametrize(
    "source",
    [
        'import value from "@/ee/config";',
        'import legacy = require("@/ee/config"); legacy();',
        "import unresolved = UnknownNamespace; unresolved();",
        'export { value } from "@/ee/config";',
        'const value = import("@/ee/config");',
        "const value = import(path);",
        'const value = require("@/ee/config");',
        'const load = require; const value = load("@/ee/config");',
        'eval("loaderCode");',
    ],
)
def test_typescript_executable_enterprise_import_is_rejected(source: str) -> None:
    result = checker().inspect_typescript(ROOT, Path("candidate.ts"), source)
    assert result["failures"], result


def test_typescript_safe_import_equals_reports_dependency() -> None:
    result = checker().inspect_typescript(
        ROOT,
        Path("candidate.ts"),
        'import safe = require("node:fs"); safe.readFileSync("local-file");',
    )
    assert result["failures"] == []
    assert result["dependencies"] == ["node:fs"]


def test_typescript_prose_does_not_hide_safe_dependency() -> None:
    result = checker().inspect_typescript(
        ROOT,
        Path("candidate.ts"),
        '// Do not import("@/ee/config").\nimport type { User } from "@/lib/types";',
    )
    assert result["failures"] == []
    assert result["dependencies"] == ["@/lib/types"]


def test_review_template_has_private_nonroot_bounded_services() -> None:
    import subprocess

    script = """
const parsed = Bun.YAML.parse(await Bun.file('deployment/docker_compose/docker-compose.orgmesh-enterprise.yml').text());
for (const [name, service] of Object.entries(parsed.services)) {
  if (service.ports || service.network_mode) throw new Error(name + ' exposes a host route');
  if (service.user !== '10001:10001') throw new Error(name + ' has an unsafe UID');
  for (const volume of service.volumes || []) {
    if (volume.bind.create_host_path !== false) throw new Error(name + ' creates a mount');
    if (!['/run/orgmesh-enterprise','/etc/orgmesh-enterprise/branding.json'].includes(volume.target)) throw new Error(name + ' shares unrelated files');
    if (name !== 'orgmesh_enterprise' && volume.read_only !== true) throw new Error(name + ' has a writable shared mount');
  }
}
const go = parsed.services.orgmesh_enterprise;
if (!go.read_only || go.restart !== 'no' || go.mem_limit !== '256m' || go.pids_limit !== 64 || go.cpus !== 0.5) throw new Error('service resource/security bounds are missing');
if (!go.cap_drop.includes('ALL') || !go.security_opt.includes('no-new-privileges:true')) throw new Error('service capabilities are unbounded');
if (!go.healthcheck.test.join(' ').includes('--unix-socket')) throw new Error('health uses a network listener');
if (!go.environment.ORGMESH_ENTERPRISE_DATABASE_URL.includes(':?')) throw new Error('DB approval is optional');
console.log('PASS: parsed private, nonroot, bounded review template');
"""
    result = subprocess.run(
        ["bun", "-e", script],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
