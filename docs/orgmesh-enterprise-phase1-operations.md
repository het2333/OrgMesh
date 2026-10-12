# OrgMesh enterprise phase-one operations

## Release scope and current acceptance

This phase adds independent branding, branding-change audit, and aggregate usage paths.
It keeps Community authentication and business-table ownership in Python.
It does not clear every inherited application path of EE dependencies.
It does not certify strict clean-room development or grant legal clearance.
Existing repository and third-party notices remain in place.

The three new Python switches default to `false`:

- `ORGMESH_ENTERPRISE_BRANDING_ENABLED`
- `ORGMESH_ENTERPRISE_AUDIT_ENABLED`
- `ORGMESH_ENTERPRISE_USAGE_ENABLED`

The audit switch controls queries and the audit page.
It does not disable transaction audit for successful branding writes.
Usage requires the usage switch in Python API, producer, and Go.
Phase one rejects multi-tenant enablement and mismatched configured organizations.

The first delivery had offline checks. The dedicated cloud run now passes real database and socket checks.
See [the cloud validation record](orgmesh-enterprise-phase1-cloud-validation-2026-10-12.md) for commands and limits.
Authenticated app, browser, full frontend test, and production-build acceptance remain incomplete.
The previous execution environment denied AF_UNIX creation with `EPERM`.
PostgreSQL binaries and a running service were absent.
The separate PostgreSQL probe returned connection refused at `127.0.0.1:5432`.
These facts do not establish a general TCP prohibition.
Some inherited full-backend test imports were also unavailable.
Do not treat collection, compilation, or disabled tests as runtime acceptance.

## Review-only deployment templates

Review `deployment/Dockerfile.orgmesh-enterprise` and the enterprise Compose overlay.
Do not apply them to an existing deployment without separate approval.
The overlay adds no host TCP port. An inherited base can still expose ports.
Inspect the complete merged configuration before approving a deployment.
The overlay is not a new, complete Community stack.
It does not create database users, passwords, networks, or a socket directory.
It proposes UID `10001` for Go, Python API, and the producer.
Confirm that every process with this UID belongs to the same trust boundary.
Confirm existing Python images and approved data mounts support this UID.
Do not change real ownership or permissions to force the template to run.

Prepare one approved private socket directory before any deployment action.
Its owner must match UID `10001`; its mode must be `0700`.
Only Go, Python API, and the producer receive this directory.
Python mounts it read-only. The Go-created socket has mode `0600`.
The service checks peer UID and short-lived operation context.
Peer UID does not identify individual processes with the same UID.
There is no TCP fallback. A failed boundary must stop deployment.

Use an approved, existing database network without host port publication.
Supply only `ORGMESH_ENTERPRISE_DATABASE_URL` to Go.
Approve a database identity restricted to the owned schema before enabling service startup.
Review its `CREATE SCHEMA` and schema-ownership needs with the database administrator.
Do not grant Community schema writes. Do not reuse a broad Community owner by convenience.
Do not add a database role or permission grant from this template.
Keep connection values out of committed files and diagnostic output.
The Go pool has at most eight database connections.
Startup checks the database and applies checksum-tracked owned-schema migrations.
The service never falls back to Community connection variables.

The Go container uses a read-only root filesystem, no added capabilities, and a nonroot UID.
It has a 256 MiB memory limit, 0.5 CPU limit, and 64-process limit.
It does not restart automatically after startup failure.
Readiness uses curl over the private UDS. It returns no settings or credentials.
A missing database, migration mismatch, unsafe socket path, or unsupported platform stops startup.
Investigate the exact failure. Do not widen permissions or add a listener to bypass it.
Inspect stale socket files before any approved removal.

Resolve official image digests before an approved build.
Keep Go module licenses, patent grants, and installed image copyright files.
Check the actual package inventory and base-image obligations before distribution.
The current task did not build or inspect a runtime image.
See `services/orgmesh-enterprise/RUNTIME-NOTICES.md` for the image notice gate.

## Owned migrations and retained data

The service applies two migrations in `orgmesh_enterprise` only.

- `001_branding.sql`: branding configuration, receipts, and transaction audit
- `002_usage.sql`: sync state, staging rows, batches, and published usage rows

The service metadata table tracks each migration version, name, and checksum.
Repeated migrations retain data. Changed checksums and unknown versions fail startup.
Tenant identifiers qualify business keys and queries.
Python keeps the sole write responsibility for Community business and usage tables.

Snapshot publication replaces the covered current projection.
Replay does not add counters. Retained staging and batches still consume space.
A complete periodic snapshot can retain up to 64 MiB and 100,000 rows per revision.
Frequent snapshots can grow staging storage quickly.
No automatic deletion or retention job exists in this phase.
Approve retention, backup, restore, access, and capacity policies before production enablement.
Do not delete tables or historical audit records as recovery.

## Recovery procedure for an authorized isolated stack

Use a local, single-organization Community test stack with existing approved test authentication.
Use a verified integration-mode mock model and existing indexed search fixture.
Do not request a real LLM key for these tests.
Do not run the default Playwright global setup under this authorization.
That setup can create accounts and PATs.
These recovery tests use existing admin storage state and create no credential or account.
They can write test branding and mock chat messages in the isolated stack.
Keep the seeded usage source unchanged during the replay check.

Before enablement, approve a plain JSON static branding file.
The file contains only `name`, `greeting`, and reviewed `logo_asset_id`.
Do not fetch remote logos or migrate static branding from an EE service.
Set `ORGMESH_ENTERPRISE_STATIC_BRANDING_FILE` to that approved file in Python.
The static view has version zero. The static contract version is one.
Without a file, the approved default is `OrgMesh`, an empty greeting, and `orgmesh-default`.

Only an authorized operator prepares each recovery phase.
The tests do not stop containers, change flags, restart workers, or alter database settings.
An operator must also reload the affected API and producer configuration.
Changing an environment file alone does not update a running process.

1. Prepare `branding-no-audit`: branding and usage on; audit queries off.
2. Run the branding test. It writes one branding version and records local evidence.
3. Prepare `enabled`: all three switches on. Run the audit and snapshot capture test.
4. Prepare `go-outage`: stop only the private Go service in the isolated stack.
5. Run the outage test. Verify static branding, mock chat, and existing search retrieval.
6. Prepare `db-outage`: restore Go and fault only its database access through approved isolation.
7. Keep the Community database available. Repeat the outage test.
8. Prepare `disabled`: close all three switches and reload API and producer.
9. Run the disabled and outage tests. Keep static files, new tables, and audit records.
10. Prepare `reenabled`: restore the private service and its approved database access.
11. Restore all three switches. Replay the unchanged complete snapshot.
12. Run the replay test. Check unchanged groups, retained branding, and nondecreasing revision.

Do not restore unrelated schemas, drop new tables, or reset counters during this workflow.
The Go database tests assert repeat migrations, retained staging, and exact replay when run.
Their runtime acceptance remains pending in this environment.
The Python producer unit test proves no source connection opens when usage is disabled.
The live disabled test verifies the visible API gates. It cannot observe database reads by itself.
The browser tests verify real chat and retrieval only in their prepared phase.
Use the named phase filter. Running all phases against one state must fail.
The replay comparison requires an unchanged source and the captured coverage window.

## Commands and prerequisites

Run commands from the repository root unless a command changes directories.
Use the approved prepared Go 1.27.1, Python 3.13 environment, and Bun 1.4.3.
The frontend dependencies must already be installed from the pinned lockfile.
Set `PYTHONPATH=backend` and `LICENSE_ENFORCEMENT_ENABLED=false` for Community checks.
Do not install a broad model stack to repair unrelated harness imports.

Offline checks:

```sh
python tools/check_orgmesh_enterprise_boundaries.py
uv run --frozen --no-sync pytest -q backend/tests/unit/orgmesh/test_enterprise_*.py
cd services/orgmesh-enterprise
go test ./...
go test -race ./...
go vet ./...
go test -race -tags=integration -run '^$' ./...
```

The checker reports files, direct imports, dynamic imports, and Go transitive dependencies.
It uses Python AST and the installed SWC TypeScript parser.
Default mode also runs actual BFF HTTP and browser client network regressions.
The private transport is mocked in these offline tests because the UDS is unavailable here.
The runtime probe blocks `ee` imports before loading the real new Community routes.
The checker does not analyze all inherited application dependencies or prove arbitrary code safe.
`--static-only` is an inventory mode. It does not prove HTTP behavior.

Use two fresh, disposable PostgreSQL databases with approved test identities.
Each database name must match `orgmesh_enterprise_test_[a-z0-9_]+`.
Neither database may contain `orgmesh_enterprise` before its test process.
The second database must also lack `public.orgmesh_recovery_legacy_fixture`.
The tests refuse existing objects. They do not create databases, roles, or credentials.
They leave migrated schemas in place.
Only test-tenant rows and owned temporary trigger fixtures are removed by existing tests.
The recovery migration test leaves its explicit legacy fixture for inspection.
Confirm database identities before any separate, approved disposal action.

```sh
cd services/orgmesh-enterprise
ORGMESH_TEST_DATABASE_URL='<approved fresh database connection>' \
ORGMESH_RECOVERY_DATABASE_URL='<approved second fresh database connection>' \
  go test -race -tags=integration ./... -count=1
go test -race -tags=transportintegration ./internal/ipc -count=1
```

The migration test hashes legacy fixture data, columns, public object inventory, constraints, and indexes.
It compares the hash after initial and repeated owned-schema migration.
This controlled fixture proof does not substitute for a real deployment backup comparison.
The transport tests require Linux UDS creation and same-UID peer checks.
A missing prerequisite fails these gates. It is not a skipped pass.

Real source and inherited API checks:

```sh
uv run --frozen --no-sync pytest -q backend/tests/external_dependency_unit/orgmesh/test_enterprise_snapshot.py
uv run --frozen --no-sync pytest -q backend/tests/integration/tests/orgmesh/test_enterprise_api.py
```

The inherited API harness needs its full supported environment and already authorized authentication fixtures.
Its restricted-admin PAT case needs an existing approved token; it does not mint one.
Credential or account provisioning remains outside this phase's current authorization.

For the new staged recovery runner, supply:

- `BASE_URL`: the local frontend origin, usually `http://localhost:3000`
- `ORGMESH_TEST_AUTH_STATE`: an existing authorized admin Playwright storage-state file
- `ORGMESH_RECOVERY_BASELINE_FILE`: a dedicated local evidence JSON path
- `ORGMESH_RECOVERY_EXPECTED_STATIC_FILE`: the approved static-brand JSON path
- `ORGMESH_RECOVERY_MOCK_LLM_APPROVED=true`: only after checking the integration-mode mock provider
- `ORGMESH_RECOVERY_SEARCH_DOCUMENT_ID`: the existing indexed recovery fixture's document ID
- `ORGMESH_RECOVERY_PHASE`: the prepared phase from the workflow above

Treat storage-state cookies as credentials. Never commit or attach that file.
The evidence file has branding and aggregate usage only. Review it before sharing.

```sh
uv run --frozen --no-sync pytest --noconftest -q \
  backend/tests/integration/tests/orgmesh/test_enterprise_recovery.py \
  -k test_branding_without_audit_ui_still_records
# Change the operator-prepared phase and select the next named test.
```

Use `--noconftest` for this dedicated runner to avoid the unrelated provisioning harness.
This changes only test collection, not production behavior or an access restriction.
A missing existing session, phase, fixture, app, or service is a test failure.

Frontend checks:

```sh
cd web
bun run test --runInBand
bun run types:check
bun run lint
bun run build
bun run playwright tests/e2e/orgmesh/enterprise-branding.spec.ts \
  tests/e2e/orgmesh/enterprise-audit.spec.ts \
  tests/e2e/orgmesh/enterprise-usage.spec.ts \
  tests/e2e/orgmesh/enterprise-regression.spec.ts --list
```

Collection does not run browser tests or global setup.
Use the existing-session configuration for approved real browser execution:

```sh
cd web
bun run playwright --config=playwright.orgmesh-recovery.config.ts \
  tests/e2e/orgmesh/enterprise-regression.spec.ts -g 'Go outage'
```

The configuration disables global provisioning and uses the supplied existing storage state.
It can also run the other three enterprise files after preparing their required isolated state.
The usage file has UI network scenarios; it does not prove real source publication.

## Build evidence and limits

The earlier normal Next build reached optimized compilation and died with exit 137.
Its cause is unknown. A later memory snapshot does not establish the earlier cause.
Keep that normal-build failure separate from later resource-bounded diagnostic results.
The first webpack diagnostic found a missing generated Opal CSS export.
The installed workspace link and pinned upstream scripts confirmed a preparation gap.
The existing CSS bundle step passed and restored the package export.
The full Opal prepare step still failed when its DTS process received SIGKILL.
The separately approved webpack retry also received SIGKILL during optimized compilation.
These signal failures have no verified cause. No full production build pass is claimed.
Coordinate with other heavy work before a final build diagnostic.
Use supported local memory diagnostics and a shared heavy-work lock.
Keep at least 1 GiB free disk space. Do not run unauthorized cleanup.
Keep backend URLs local, telemetry disabled, and Sentry credentials and DSN unset.
Do not upload traces or change security/network settings.
A webpack diagnostic is a different bundler from the normal build and cannot clear its failure.

Record each gate as PASS, FAIL, or UNRUN with the exact command and reason.
Do not call this phase runtime-accepted while real DB, UDS, app, browser, or image gates remain pending.
