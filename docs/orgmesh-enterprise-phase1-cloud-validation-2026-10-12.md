# Dedicated cloud validation, 2026-10-12

The new Go service passes real PostgreSQL and private-transport checks in this cloud environment.
Full application acceptance remains incomplete. The table distinguishes each gate.

The delivered commit is `73fdfbacc87a1073f88004d3b55bc72f8e63e2d9`.
Its tree is `7ead6484bdef3f3add617b5ca0258fcb2e44e85f`.
Its parent is `dfd891f3d4e864f8abeef45c6b09469bf2a7809e`.
The branch is `feature/orgmesh-go-enterprise-phase1`.
The original checkout remains unchanged. No merge or deployment occurred.

## Verified gates

| Gate | Result | Evidence |
| --- | --- | --- |
| Go module unit tests | PASS | `go test ./...` |
| Go real PostgreSQL race integration | PASS | `go test -race -tags=integration ./... -count=1 -v` |
| Linux private transport race tests | PASS | `go test -race -tags=transportintegration ./internal/ipc -count=1 -v` |
| Go static checks | PASS | `go vet ./...` |
| Go executable build | PASS | `go build ./cmd/enterprised` |
| Python phase-one unit tests | PASS | 184 tests; one inherited Starlette deprecation warning |
| Python real PostgreSQL source checks | PASS | Five tests in `test_enterprise_snapshot.py` |
| New-path boundary checks | PASS | 275 inventory entries; HTTP and browser-client network regressions ran |
| Shared package preparation | PASS | Pinned `build` script; inherited token-collision warnings |
| Opal preparation | PASS | Pinned `build` script; ESM, DTS, and CSS output |
| Frontend types | PASS | `bun run types:check`; coverage 98.91% |
| Frontend lint | PASS | `bun run lint`; inherited warnings remain |
| Scoped enterprise frontend checks | PASS | 78 tests in five files with an explicit 15-second test limit; the normal full-suite gate remains failed |
| Full Community app module import | PASS | Import only; startup and login were not verified |
| Browser environment | PASS | Pinned Playwright launches system Chromium and executes JavaScript |
| Enterprise browser collection | PASS | 13 tests in four files; collection does not run them |
| Authenticated app and browser checks | UNRUN | Existing approved sessions, restricted PAT, and recovery search fixture are absent |

The PostgreSQL suite verifies branding, audit, and receipt atomicity with real failure triggers.
It also verifies version concurrency, retry receipts, tenant isolation, and stable audit pagination.
Usage checks cover fencing, replay, reset, corrections, publication atomicity, and capacity limits.
The capacity tests write the full row and byte limits in disposable databases.

The legacy-schema hash query failed on PostgreSQL 15 before any migration ran.
`pg_class.relkind` uses an internal character type with ambiguous text concatenation.
The test now casts that value to text. No production migration or schema definition changed.
The test failed before this fix, then passed on a fresh database.
The complete race integration suite also passed after the fix.
The fixture structure and data hash remained unchanged after initial and repeated migrations:
`871297ce94fd540decebb723f078e4aaa362777b490c4a451f33c34b28d556a6`.

Eleven additional real Go/Python/UDS/PostgreSQL checks passed in the evidence package.
They cover branding and audit, idempotent replay, context rejection, activation waiting, and precise collection.
They also cover snapshot replacement, restart retention, source corrections, and empty snapshots.
Real locks verify source deadlines, retained publication, bounded service failure, and recovery.
An incomplete HTTP header is closed by the configured private-transport timeout.
These checks use explicit isolated fixtures. They do not claim app-authentication or visual acceptance.

## Failed and blocked gates

| Gate | Result | Exact limit |
| --- | --- | --- |
| Normal full frontend tests | FAIL | 169 suites: 165 passed, four failed; 1472 tests: 1453 passed, 19 failed |
| Isolated retry of four failed suites | FAIL | 81 passed, two timed out: account switch and custom model configuration |
| Account-switch timeout diagnostic | PASS | Single test passes with a 15-second limit; it does not clear the full-suite gate |
| Custom-model timeout diagnostic | FAIL | The same test fails on the original baseline with a 15-second limit |
| Normal production build | FAIL | Turbopack cannot fetch DM Mono and Hanken Grotesk from Google Fonts |

The exact Google Fonts URL also failed through the existing proxy with `403 Forbidden`.
No proxy bypass, TLS relaxation, or network permission change was attempted.
The normal build recorded no cgroup OOM or OOM kill. This does not explain the previous environment's exit 137.
No webpack or mocked-font build is presented as a normal production-build pass.

The environment has no approved `USER_AUTH_SECRET`, current admin/member sessions, or restricted-admin PAT.
It also lacks the existing indexed fixture required for mock chat and search recovery.
No account, credential, PAT, or permission grant was created to clear these gates.
The default Playwright provisioning setup was not run.
Use the existing-session runner once the approved local stack and credentials are available.

An independent read-only review found no Critical or Important defect in the five plan review targets.
That result does not replace the failed or unrun gates above.
The boundary checker covers new paths and Go dependencies, not every inherited application dependency.

## Reproduction

Use Go 1.27.1, Python 3.13.5, PostgreSQL 15.2, and the repository-pinned Bun 1.3.13.
Keep tool caches in a writable task directory. Put Bun and Go on `PATH`.
Set `PYTHONPATH=backend` and `LICENSE_ENFORCEMENT_ENABLED=false` for Community checks.

The frozen default Python sync could not reach the registry URLs recorded in the lockfile.
Its default groups also include the model-server stack.
This run used the supported frozen export for `backend` and `dev`, then hash-verified official PyPI installation.
It kept all versions and hashes. It did not modify either dependency lockfile.

```sh
uv export --frozen --no-default-groups --group backend --group dev \
  --no-emit-index-url --format requirements-txt --output-file /tmp/orgmesh-backend.txt
uv pip sync --python .venv/bin/python --require-hashes \
  --index-url https://pypi.org/simple /tmp/orgmesh-backend.txt
```

Use a fresh disposable database for each Go integration process.
Supply `ORGMESH_TEST_DATABASE_URL` and `ORGMESH_RECOVERY_DATABASE_URL` with approved test connections.
Both names must match `orgmesh_enterprise_test_[a-z0-9_]+`.
The tests retain their schema and the legacy recovery fixture for inspection.
Do not reuse an occupied database or delete its objects to force a pass.

The complete evidence package contains commands, logs, failure names, fixture scripts, and a gate matrix.
It excludes credentials, browser storage-state files, and screenshots.
