#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Check only the new enterprise paths. Default mode also runs HTTP regressions."""

import argparse
import ast
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


def inspect_python(path: Path, source: str) -> dict[str, Any]:
    dependencies: set[str] = set()
    failures: list[str] = []
    import_modules = {"importlib"}
    import_functions = {"__import__"}
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as error:
        return {"file": str(path), "dependencies": [], "failures": [str(error)]}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                dependencies.add(alias.name)
                if alias.name == "importlib":
                    import_modules.add(alias.asname or alias.name)
        elif isinstance(node, ast.ImportFrom):
            module = "." * node.level + (node.module or "")
            dependencies.add(module)
            if node.module == "importlib":
                for alias in node.names:
                    if alias.name == "import_module":
                        import_functions.add(alias.asname or alias.name)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.NamedExpr)):
            value = node.value
            if (isinstance(value, ast.Name) and value.id in import_functions) or (
                isinstance(value, ast.Attribute)
                and isinstance(value.value, ast.Name)
                and value.value.id in import_modules
                and value.attr == "import_module"
            ):
                failures.append(f"line {node.lineno}: indirect executable loader alias")
        if not isinstance(node, ast.Call):
            continue
        function = node.func
        if isinstance(function, ast.Name) and function.id in ("exec", "eval"):
            failures.append(
                f"line {node.lineno}: executable code generation is unsupported"
            )
        dynamic = (
            isinstance(function, ast.Name) and function.id in import_functions
        ) or (
            isinstance(function, ast.Attribute)
            and isinstance(function.value, ast.Name)
            and function.value.id in import_modules
            and function.attr == "import_module"
        )
        if dynamic:
            if (
                node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                dependencies.add(node.args[0].value)
            else:
                failures.append(f"line {node.lineno}: unresolved executable import")
    failures.extend(
        f"forbidden dependency {dependency}"
        for dependency in sorted(dependencies)
        if "ee" in dependency.split(".")
    )
    return {
        "file": str(path),
        "dependencies": sorted(dependencies),
        "failures": failures,
    }


def inspect_typescript(root: Path, path: Path, source: str) -> dict[str, Any]:
    result = subprocess.run(
        [
            "node",
            str(root / "tools/check_orgmesh_enterprise_typescript.cjs"),
            str(root),
        ],
        input=json.dumps({"file": str(path), "source": source}),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if result.returncode:
        return {
            "file": str(path),
            "dependencies": [],
            "failures": [result.stderr.strip()],
        }
    return json.loads(result.stdout)


def inspect_go(root: Path) -> list[dict[str, Any]]:
    result = subprocess.run(
        ["go", "list", "-deps", "-json", "./..."],
        cwd=root / "services/orgmesh-enterprise",
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        env=os.environ | {"GOTOOLCHAIN": "local", "GOPROXY": "off"},
    )
    if result.returncode:
        return [
            {
                "file": "go dependency graph",
                "dependencies": [],
                "failures": [result.stderr.strip()],
            }
        ]
    entries: list[dict[str, Any]] = []
    decoder = json.JSONDecoder()
    remaining = result.stdout.lstrip()
    while remaining:
        package, end = decoder.raw_decode(remaining)
        imports = package.get("Imports", [])
        failures = [
            f"forbidden dependency {item}"
            for item in imports
            if "ee" in item.split("/")
        ]
        entries.append(
            {
                "file": package["ImportPath"],
                "dependencies": imports,
                "failures": failures,
            }
        )
        remaining = remaining[end:].lstrip()
    return entries


def check_paths(root: Path) -> list[dict[str, Any]]:
    python_paths = set((root / "backend/onyx/orgmesh_enterprise").glob("*.py"))
    python_paths.update(
        (root / "backend/onyx/server/features/orgmesh_enterprise").glob("*.py")
    )
    python_paths.update(
        root / path
        for path in (
            "backend/onyx/db/orgmesh_usage_snapshot.py",
            "backend/onyx/db/engine/orgmesh_snapshot.py",
            "backend/onyx/background/celery/tasks/orgmesh_enterprise_tasks.py",
        )
    )
    web_paths = set((root / "web/src/lib/orgmesh-enterprise").glob("*.ts*"))
    web_paths.update((root / "web/src/app/admin/orgmesh-enterprise").rglob("*.tsx"))
    web_paths.update((root / "web/src/views/admin").glob("OrgMesh*Page.tsx"))
    inventory = [
        inspect_python(path.relative_to(root), path.read_text())
        for path in sorted(python_paths)
    ]
    inventory.extend(
        inspect_typescript(root, path.relative_to(root), path.read_text())
        for path in sorted(web_paths)
        if ".test." not in path.name
    )
    return inventory + inspect_go(root)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument(
        "--static-only",
        action="store_true",
        help="inventory only; does not prove runtime HTTP behavior",
    )
    args = parser.parse_args()
    root = args.root.resolve()
    try:
        inventory = check_paths(root)
    except (OSError, subprocess.SubprocessError, ValueError) as error:
        print(json.dumps({"status": "FAIL", "reason": str(error)}))
        return 1
    checks: list[dict[str, Any]] = []
    if not args.static_only:
        commands = [
            [
                "uv",
                "run",
                "--frozen",
                "--no-sync",
                "pytest",
                "-q",
                "backend/tests/unit/orgmesh/test_enterprise_recovery.py",
            ],
            [
                "bun",
                "run",
                "--cwd",
                "web",
                "test",
                "--runInBand",
                "--runTestsByPath",
                "src/lib/orgmesh-enterprise/boundaries.test.ts",
            ],
        ]
        for command in commands:
            try:
                result = subprocess.run(
                    command,
                    cwd=root,
                    capture_output=True,
                    text=True,
                    timeout=180,
                    check=False,
                    env=os.environ
                    | {"LICENSE_ENFORCEMENT_ENABLED": "false", "PYTHONPATH": "backend"},
                )
                checks.append(
                    {
                        "command": command,
                        "exit_code": result.returncode,
                        "output": result.stdout + result.stderr,
                    }
                )
            except (OSError, subprocess.SubprocessError) as error:
                checks.append(
                    {"command": command, "exit_code": 1, "output": str(error)}
                )
    failed = any(item["failures"] for item in inventory) or any(
        item["exit_code"] for item in checks
    )
    print(
        json.dumps(
            {
                "status": "FAIL" if failed else "PASS",
                "scope": "new direct paths plus Go transitive dependencies; inherited app is not cleared",
                "runtime_checked": not args.static_only,
                "inventory": inventory,
                "behavior_checks": checks,
            },
            indent=2,
        )
    )
    return int(failed)


if __name__ == "__main__":
    sys.exit(main())
