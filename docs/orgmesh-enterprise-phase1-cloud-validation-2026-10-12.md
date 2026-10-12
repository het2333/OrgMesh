# Dedicated cloud validation, 2026-10-12

Real PostgreSQL, private transport, Community login, and phase-one browser checks pass in this cloud environment.
The normal Turbopack production build also passes with local licensed fonts.
Full acceptance remains incomplete. The tables distinguish failures and unrun checks.

The cloud-restored source commit is `73fdfbacc87a1073f88004d3b55bc72f8e63e2d9`.
Its tree is `7ead6484bdef3f3add617b5ca0258fcb2e44e85f`.
Its parent is `dfd891f3d4e864f8abeef45c6b09469bf2a7809e`.
Work uses `feature/orgmesh-go-enterprise-phase1` in an isolated checkout.
The original checkout remains unchanged. No merge or deployment occurred.
The package manifest records the final corrective commit and tree.

## Verified gates

| Gate | Result | Evidence |
| --- | --- | --- |
| Go module unit tests and static checks | PASS | `go test ./...` and `go vet ./...` |
| Go real PostgreSQL race integration | PASS | `go test -race -tags=integration ./... -count=1 -v` |
| Linux private transport race tests | PASS | `go test -race -tags=transportintegration ./internal/ipc -count=1 -v` |
| Go executable build | PASS | `go build ./cmd/enterprised` |
| Python phase-one unit tests | PASS | 188 tests; one inherited Starlette warning |
| Python real PostgreSQL source checks | PASS | Five tests in `test_enterprise_snapshot.py` |
| New-path boundary checks | PASS | 275 inventory entries; transport and browser-client network regressions ran |
| Shared and Opal preparation | PASS | Pinned builds; ESM, DTS, and CSS output |
| Frontend types and lint | PASS | Type coverage 98.91%; inherited lint warnings |
| Phase-one frontend checks at default limits | PASS | All 78 tests in five files pass in the final normal full run |
| Normal production build | PASS | `bun run build`; compilation, TypeScript, static generation, and route output |
| Community schema migration | PASS | Fresh task-owned PostgreSQL database migrated through head |
| Community startup and basic login | PASS | Both legacy enterprise flags disabled; normal admin and ordinary-user login |
| Existing phase-one browser scenarios | PASS | 10 tests; production frontend and system Chromium; standard assertion limits |
| Real private API authorization | PASS | Anonymous and ordinary-user private operations return 403 |
| Real published usage in browser | PASS | Community source, read-only collector, Go, PostgreSQL, and browser; four privacy categories |
| Actual browser account change | PASS | Switching to the ordinary-user session hides the prior private snapshot |
| Live automatic refresh | PASS | A real usage-summary request occurs on the 15-second interval |
| Browser stale threshold | PASS | Real persisted snapshot; controlled browser clock crosses 120 seconds |
| Real Go outage | PASS | Stale current-query data retained; changed-query data cleared; login and static brand remain available |
| Real enterprise database outage | PASS | Go-owned database refuses connections; Community authentication and static brand remain available |
| Database recovery | PASS | Restored database connections expose the persisted dynamic brand |
| Disabled-feature startup | PASS | Community authentication and static brand work; private endpoints and query controls are gated |
| Real scheduled collection | PASS | Repository Beat, Redis, primary worker, private Go socket, and PostgreSQL; revisions 7 to 9 |
| Real OpenSearch keyword client | PASS | Repository-pinned OpenSearch and a public synthetic index fixture |

The PostgreSQL suite verifies branding, audit, and receipt atomicity with real failure triggers.
It also verifies version concurrency, retry receipts, tenant isolation, and stable audit pagination.
Usage checks cover fencing, replay, reset, corrections, publication atomicity, and capacity limits.
The capacity tests write the full row and byte limits in disposable databases.

Eleven additional Go/Python/UDS/PostgreSQL checks pass in the evidence package.
They cover activation waiting, exact amounts, snapshot replacement, restart retention, corrections, and empty snapshots.
Real locks verify source deadlines, retained publication, bounded service failure, and recovery.
An incomplete private HTTP header is closed by the configured transport timeout.

## Corrections

The PostgreSQL 15 recovery test failed before any migration ran.
`pg_class.relkind` uses an internal character type with ambiguous text concatenation.
The test now casts that value to text. No production migration changed.
The targeted check and complete race integration suite pass after this correction.
The legacy fixture structure and data hash remain unchanged after repeated migrations:
`871297ce94fd540decebb723f078e4aaa362777b490c4a451f33c34b28d556a6`.

Python previously ignored the server socket override during real route construction.
`ORGMESH_ENTERPRISE_SOCKET_PATH` now selects the matching private Go socket.
Existing clean absolute-path validation remains in effect. Invalid overrides fail closed.
Four new route-configuration cases failed before the correction and pass afterward.
The default socket and private directory requirements remain unchanged.

Google Fonts downloads failed through the existing proxy with 403 responses.
The same selected font families now load through `next/font/local`.
Official Google Fonts binaries are unchanged. Their full SIL Open Font License files accompany them.
The provenance manifest records the upstream commit, paths, sizes, and SHA256 values.
Existing font assets, copyright text, and licenses remain present.
The normal production build and browser font loading pass after this correction.
No proxy bypass, TLS relaxation, mocked font loader, or alternate bundler is used for that build.

Seven browser failures matched both the application alert and Next's route announcer.
The page objects now select the alert containing the existing expected message.
All original message and visibility assertions remain. All 10 scenarios pass after this correction.
The recovery page opens the existing compose route instead of the workspace home page.

## Failed and unrun gates

| Gate | Result | Exact limit |
| --- | --- | --- |
| Normal full frontend tests | FAIL | 169 suites: 167 pass, two fail; 1472 tests: 1465 pass, seven fail; no skips |
| Community mock-chat rendering | FAIL | Backend attempts the default Hugging Face tokenizer download; current proxy returns 403 |
| Full search-enabled Community startup | FAIL | OpenSearch initializes, but embedding-model construction requires the same unavailable tokenizer |
| Three complete chat-and-search recovery scenarios | UNRUN | The two failures above prevent their combined application assertions |
| Real restricted-PAT authorization | UNRUN | No approved restricted PAT is present; no PAT was created |
| Real multiple-organization browser sessions | UNSUPPORTED | Phase one explicitly supports one configured organization; mocked context-switch UI and real tenant rejection checks pass |
| Screenshot or visual-equivalence review | UNRUN | Functional browser checks and font loading do not establish pixel equivalence |

The package retains normal frontend failures and baseline comparisons.
Earlier runs varied under concurrent service preparation. No timeout was increased for the final full-suite gate.
The final failures contain six CustomModal cases and one skill-import case.
The original baseline reproduces the CustomModal failures and several SkillEditor failures.
The skill-import component and its test are unchanged from the baseline.
Its three isolated tests pass on both baseline and current source with normal limits.
Its final full-suite timeout remains unresolved. The suite gate stays failed.
The account-switch test passes at its normal limit in the earlier quiet full run.
The final matrix records the last complete normal run and each scoped result.

The OpenSearch fixture uses constant test vectors and verifies only real keyword retrieval through the repository client.
It does not establish application-route retrieval, semantic search, indexing workers, or chat recovery.
The missing tokenizer is `nomic-ai/nomic-embed-text-v1/tokenizer.json` from its official Hugging Face repository.
A supported model cache or approved access to that resource is needed for the full application flow.
The existing proxy and authentication controls were not changed.

Basic login uses repository test passwords in a disposable Community database.
Integration mode permits an unset reset/OAuth signing secret; password, session, and permission checks still run.
No password-reset, OAuth, captcha, or production-secret acceptance is claimed.
Browser auth state remains outside the evidence directory and is removed after validation.
The task-owned Community database is removed after validation, including its short-lived sessions and synthetic accounts.
Migration and recovery test databases remain in the stopped task volume for inspection.
An initial worker teardown stopped the broker too early and emitted a logging recursion error.
The shutdown check passed with exit zero when the broker stayed available until the worker finished.
No production database, durable credential, PAT, or new permission grant is used.
The default Playwright provisioning setup is not run.

Independent read-only reviews found no Critical or Important issue in the source corrections and alert assertions.
Those reviews do not replace failed or unrun gates.
The boundary checker covers new paths and Go dependencies, not every inherited application dependency.

## Reproduction

Use Go 1.27.1, Python 3.13.5, PostgreSQL 15.2, repository-pinned Bun 1.3.13, and system Chromium.
Use writable task directories for tool caches. Put Bun and Go on `PATH`.
Prepare the shared package and Opal with their standard build scripts before the frontend build.
Use one heavy build or test process at a time.
Set `LICENSE_ENFORCEMENT_ENABLED=false` and `ENABLE_PAID_ENTERPRISE_EDITION_FEATURES=false` for Community checks.
Match the Python socket override to the Go `--socket` argument.

The frozen default Python sync cannot reach the registry URLs recorded in the lockfile.
This run uses a frozen export for `backend` and `dev`, followed by hash-verified official PyPI installation.
It keeps all versions and hashes. Neither dependency lockfile changes.

```sh
uv export --frozen --no-default-groups --group backend --group dev \
  --no-emit-index-url --format requirements-txt --output-file /tmp/orgmesh-backend.txt
uv pip sync --python .venv/bin/python --require-hashes \
  --index-url https://pypi.org/simple /tmp/orgmesh-backend.txt
```

Use fresh disposable databases for Go integration processes.
Supply approved `ORGMESH_TEST_DATABASE_URL` and `ORGMESH_RECOVERY_DATABASE_URL` connections.
Both names must match `orgmesh_enterprise_test_[a-z0-9_]+`.
Do not reuse an occupied database or delete its objects to force a pass.

Use the standard API pool capacity. Startup warms 20 sync and 20 async connections.
The earlier reduced six-connection test pool could not support that warm-up.
Use the standalone production server with copied `public` and `.next/static` directories.
For this loopback preview, the existing `OVERRIDE_API_PRODUCTION=true` option enables Next's backend proxy.
Production ingress was not deployed or tested.

The package contains complete changed source, binary-capable patches, a Git bundle, logs, fixture scripts, and gate matrices.
It excludes browser storage state, credential files, screenshots, and traces.
