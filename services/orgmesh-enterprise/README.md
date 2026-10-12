# OrgMesh enterprise service

This service writes only the `orgmesh_enterprise` PostgreSQL schema.
Python retains ownership of Community tables and authentication.
The service does not read or migrate legacy branding.

## Runtime requirements

Use Go 1.27.1 and PostgreSQL with the pinned pgx v5.11.0 driver.
Set `ORGMESH_ENTERPRISE_DATABASE_URL` to the approved enterprise database connection string.
The service does not use Community connection variables as a database fallback.
Approve database identity, permissions, retention, and backup policy before production use.
This change does not create a database role or credentials.

The database identity needs access to the service schema and its migration metadata.
Startup applies only the embedded, checksum-tracked service migrations.
A changed checksum or unsupported migration version stops startup.
Readiness checks the database connection. Health returns no configuration.

Use the same configured organization in Python and Go.
Phase one rejects `MULTI_TENANT=true`.
Configure a private Unix socket directory with mode `0700` before startup.
The socket file has mode `0600`. There is no TCP fallback.
Processes that share the server UID must be trusted.
For an isolated host checkout, pass the private path through Go's `--socket` flag.
Set the same absolute path in Python's `ORGMESH_ENTERPRISE_SOCKET_PATH`.
The default remains `/run/orgmesh-enterprise/enterprise.sock`.
Empty, relative, and unclean override paths fail configuration validation.

Python feature flags default to false.
Missing dynamic branding returns the approved Python static configuration.
The static view has version `0`. The static contract version remains `1`.
The first accepted patch creates dynamic version `1`.

## Deterministic checks

Run from this directory:

```sh
go test ./...
go test -race ./...
go vet ./...
```

These commands do not prove PostgreSQL transaction behavior.

## Isolated PostgreSQL checks

Use a new, disposable database named `orgmesh_enterprise_test_<suffix>`.
The suffix may contain lowercase letters, digits, and underscores.
The database must not contain an `orgmesh_enterprise` schema.
The tests refuse existing schemas. They never drop an unknown database or schema.
They delete only rows for tenants they create.
Temporary failure triggers exist only in this isolated test schema.

```sh
ORGMESH_TEST_DATABASE_URL='<DSN for the new disposable database>' \
  go test -tags=integration ./internal/store -count=1
```

Create a fresh disposable database for each test process.
The test process leaves its schema in place.
Delete the disposable database yourself after you confirm its identity.
Do not point this command at a production or shared database.

The tests cover config, audit, and receipt atomicity; audit-trigger failures;
concurrent first writes; retries after later updates; conflicting bodies;
unchanged writes; tenant isolation; filters; pagination; and migration checksums.
A missing test connection is a failure, not a skipped pass.

Compilation without execution is available separately:

```sh
go test -tags=integration -run '^$' ./...
```

## Audit scope

Persistent audit records cover successful branding creation and modification.
They contain actor and resource identifiers, time, result, request ID,
versions, and changed field names. They do not contain the greeting or name values.
Reads and refused requests use logs with only operation or error codes.
This service does not claim persistent audit coverage for all requests.

## Usage snapshots

Set `ORGMESH_ENTERPRISE_USAGE_ENABLED=true` in both services to enable usage calls.
It is false by default. The first successful producer begin persists the activation boundary.
See [the version-one protocol](../../contracts/orgmesh-enterprise/usage-protocol.md) for the producer and UI contract.
The receiver never reads the Community usage table.

The integration suite also covers usage lease concurrency, restart replay, expiry,
complete reset, partial coverage, atomic cursor publication, tenant isolation,
source identity checks, stored digest checks, and complete-snapshot size limits.
These tests need the disposable PostgreSQL database described above.
The 64 MiB and 100,000-row cases intentionally write large disposable snapshots.

## Recovery and deployment review

See [phase-one operations](../../docs/orgmesh-enterprise-phase1-operations.md).
The Dockerfile and Compose overlay are review-only templates.
They add no host TCP port or database identity.
Approve the matching nonroot UID, private UDS directory, and schema-only access separately.
The templates do not change a real environment.

Recovery closes all three new switches and keeps the static branding file.
Keep new tables, branding receipts, and audit records.
Reenablement replays complete snapshots without adding counters.
Staging and batches remain retained. No automatic deletion job exists.
Approve retention, backup, restore, access, and capacity before production use.

Run the boundary checker from the repository root:

```sh
python tools/check_orgmesh_enterprise_boundaries.py
```

Its default mode checks executable dependency edges and runs offline HTTP regressions.
It checks the new paths only. It does not clear inherited EE paths or certify clean-room status.
The offline UDS replacement does not prove real socket behavior.

The recovery migration test also needs a second fresh disposable database:

```sh
ORGMESH_TEST_DATABASE_URL='<approved fresh disposable database>' \
ORGMESH_RECOVERY_DATABASE_URL='<approved second fresh disposable database>' \
  go test -race -tags=integration ./... -count=1
```

Keep full runtime dependency notices in `THIRD_PARTY_NOTICES.txt`.
Keep the image notices described in `RUNTIME-NOTICES.md` when distributing a built image.
No runtime image was built in this task. Its final package and license review remains pending.
