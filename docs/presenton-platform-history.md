# Presentation platform history

This change extends the existing OrgMesh presentation bridge.
It does not replace the editor, authentication, model relay, or export routes.
Slides, export files, engine users, and engine volumes stay in Presenton.

## Scope

- Store platform task IDs and deck IDs with their owner
- Link ordinary source conversations and owned personal projects
- Keep existing engine IDs and old response keys
- Import observed legacy jobs and decks without guessing their source
- Read stored task history without contacting Presenton
- Recheck source ownership and document access when returning links

This slice provides backend persistence and a unified history page.
Open /app/tools/history from the existing tools page.
The page shows generation tasks and PPT records with source and project links.
It does not add chat-to-PPT generation buttons.
Existing upload references keep their existing ownership checks.
The new tables do not store prompts, messages, slides, or upload paths.
Deck access remains owner-scoped under the existing editor and export checks.
This slice does not make derived PPT access inherit document source ACL revocation.
Set that product policy before production enablement.

## Default behavior

ORGMESH_PRESENTON_HISTORY_ENABLED defaults to false.
The Compose presentation overlay forwards this flag to api_server.
Existing /jobs, /presentations, and /generate responses retain their shape when disabled.
The new /history route returns NOT_FOUND when disabled.
Explicit source or project fields return SERVICE_UNAVAILABLE when disabled.
They are never silently discarded.

Apply the additive migration before enabling the flag in a test deployment.
Migration b4c91a7e2d60 extends the OrgMesh revision 8266b8886041.
The source already contains another head, c7bf5721733e.
Inspect the existing migration graph and database revision first.
This change does not merge those existing branches.
No production database was modified while preparing this patch.

Disabling the flag restores the old bridge behavior.
It leaves platform history records intact.
Do not downgrade a database just to disable this feature.
Downgrade removes the new history tables and their records.

## API contracts

All paths below use the existing /orgmesh/presenton prefix.
All routes require the existing BASIC_ACCESS permission.
Database access uses the existing tenant-aware request session.

### POST /generate

The existing content, slide count, language, template, and files fields stay unchanged.
Two optional fields are available when history is enabled:

- source_chat_id: an owned ordinary chat UUID
- project_id: an owned personal project ID

A source chat with a project supplies project_id when the request omits it.
A conflicting source project is rejected.
Shared, foreign, deleted, and incognito chats cannot become source links.
The existing chat document ACL check runs before generation.

Platform metadata is not forwarded to Presenton.
The existing engine task_id remains in the response.
Enabled responses also include platform_task_id.

An enabled request stores a submitting attempt before contacting the engine.
A successful response binds the engine task ID and sets pending.
An explicit engine rejection leaves a failed platform attempt.
A process interruption or uncertain engine response leaves an unresolved attempt.
The API warns users to check jobs before repeating an uncertain request.

A DB binding failure retries the database write once.
It never repeats an accepted engine generation request.
If both DB writes fail, the response still returns the accepted engine task_id.
It also returns platform_task_id and history_status set to awaiting_sync.
The reserved source record remains unresolved until operators reconcile it.
This slice does not promise automatic recovery across prolonged database outages.
Do not repeat the generation POST to repair a history binding failure.

### GET /jobs and GET /presentations

Enabled calls synchronize only the authenticated engine user's returned records.
Database uniqueness constraints make repeated observations idempotent.
PostgreSQL transaction locks serialize polling and binding for each owner and engine task.
A poll-before-bind import merges into the original source-bearing platform attempt.
This merge preserves a completed deck and never takes another generated attempt's ID.
Stored terminal task states do not regress after stale pending responses.
Engine IDs, titles, progress data, and existing response fields remain available.

Job responses add platform_task_id, project_id, and source_chat_id.
Deck responses also add platform_presentation_id.
Source fields are null for imported records without known provenance.
Deleted or revoked source links are hidden without deleting task history.

Synchronization is request-driven.
It does not add a background worker or change the engine task retention period.
The existing /jobs fetch observes at most 50 upstream jobs per request.
Older unseen engine jobs cannot be reconstructed automatically.

### GET /history

Returns only the current user's stored task records.
It does not refresh the engine or claim a pending task has completed.
Fields include platform_task_id, task_id, presentation_id, status,
project_id, source_chat_id, created_at, and updated_at.

- limit defaults to 50 and accepts 1 through 100
- offset defaults to 0 and accepts 0 through 100000
- optional status filters submitting, pending, completed, or error before pagination
- status is submitting, pending, completed, or error
- task_id is null until the engine ID has been bound

Ordering uses creation time and platform ID for stable pagination.
Deleted engine decks can still appear in durable task history.
Opening or exporting them still uses the engine's current ownership checks.

## Verification

The isolated runner uses Python 3.13 and the repository's pinned test dependencies.
It loads the actual new ORM declarations and changed route bodies unchanged.
It uses real SQLAlchemy persistence with SQLite.
It stubs unrelated application imports and tests source authorization boundaries with mocks.
It also renders the new migration as PostgreSQL SQL without applying it.

Run the focused check:

python tools/test_presenton_history_isolated.py

Run the normal checks in a complete repository environment:

uv run pytest -xv backend/tests/unit/orgmesh/test_presentation_history.py backend/tests/unit/orgmesh/test_presentation_history_routes.py

The isolated check does not prove full application startup, real PostgreSQL concurrency,
tenant middleware behavior, live source ACL integration, or browser/editor flows.
Those checks remain necessary before deployment.

## Unified frontend history

The tools page links to /app/tools/history.
The page uses the existing Opal controls and workspace styles.
It provides task and PPT tabs, owner-scoped server status filters, and 20-item pages.
Task requests fetch one extra row to detect the next page without guessing totals.

Every data cache key includes the resolved owner.
Requests pause while the user identity is loading.
An authentication error from any data source hides cached records and source links.
The page uses the existing private chat, personal project, and presentation editor routes.
It never invents source links for imported records.

When stored history is disabled, existing engine PPTs remain available in the PPT tab.
When live task refresh fails, the task tab can show stored history with a warning.
Unconfirmed attempts warn users against duplicate generation.
Pending engine decks keep their editor button disabled.
Loading, empty, failed, disabled, and authentication states have localized messages.
All nine existing locales include the 44 history translation keys.

Focused frontend checks use actual React rendering and JSDOM.
They mock Opal, identity, localization, and SWR boundaries.
They do not prove live browser visuals or full editor navigation.

Normal frontend commands:

cd web
bun run test -- PresentationHistory history.test
bun run types:check
bun run lint

A minimal test environment can also run the focused runner:

ORGMESH_TEST_NODE_MODULES=/path/to/test/node_modules NODE_PATH=/path/to/test/node_modules node tools/test_presenton_history_web_isolated.cjs

Use the repository-pinned React, Jest, SWC, and testing-library versions.
Match the Jest environment release with the Jest runtime release.
A mismatched older Jest environment cannot run the newer runtime.

Strict TypeScript checks pass for the history utility and API types.
A broader UI type graph check found no diagnostics in the changed production files.
That broader check remains incomplete because unrelated app dependencies are absent.
The full Next build, type-coverage gate, and live browser/editor checks remain required before deployment.

## Optional Go history read model

Only `/orgmesh/presenton/history` has an optional Go projector.
Python still authenticates the user, selects the tenant, queries owner-scoped tasks, and checks source/project access.
Go receives one authorized page. It does not query, sort, paginate, cache, or contact Presenton.
Generation, binding, jobs, decks, editor, relay, and exports use the existing paths.

`ORGMESH_HISTORY_READ_BACKEND` accepts `python`, `shadow`, or `go`.
The default is `python`. Unknown values select Python and emit a fixed warning.
The history feature flag still defaults to `false`.
Shadow mode compares both projectors on the same facts and returns Python rows.
Go mode returns validated Go rows. Any timeout, unsafe socket, malformed response, or difference uses the same Python facts.
The route does not query or check ACL a second time during fallback.
Each public row retains its eight keys, explicit nulls, UUID strings, timestamp text, and SQL order.

The private endpoint uses HTTP on a Linux Unix socket only.
The default local path is `/tmp/orgmesh-history-go/history.sock`.
The socket directory must be owned by the API UID with mode `0700`.
The socket must have the same owner and mode `0600`. Symlinks and regular files are refused.
The Go listener checks Linux peer credentials and accepts only the configured API UID.
Requests and responses have a 256 KiB bound and 100-row bound.
The client has a 500 ms total timeout, no retry, no redirects, and no environment proxies.
The server bounds headers, read/write time, connections, and 32 concurrent handlers.
Logs contain only mode, outcome, and fixed reason codes.

### Manual build and checks

The verified toolchain is Go 1.27.1 on Linux amd64.
The official `go1.27.1.linux-amd64.tar.gz` SHA-256 is
`63d339f0da5ab53635a56f2490a7984dfe12dfcff22ad749f63edaf590168445`.
Check the archive against https://go.dev/dl/ before extraction.
The module uses only the standard library. No DB or Presenton credentials are supplied to Go.

From `services/orgmesh-core`, run:

```sh
GOTOOLCHAIN=local go test -race -v ./...
GOTOOLCHAIN=local go vet ./...
GOTOOLCHAIN=local go build -o /tmp/orgmesh-historyd ./cmd/historyd
```

From the repository root, use the existing Python test environment:

```sh
python tools/test_presenton_history_isolated.py
python tools/test_history_go_ipc.py --binary /tmp/orgmesh-historyd
ORGMESH_TEST_NODE_MODULES=/path/to/test/node_modules NODE_PATH=/path/to/test/node_modules node tools/test_presenton_history_web_isolated.cjs
```

The isolated runner uses real SQLAlchemy models and SQLite. Authentication and live ACL services are mocked.
A sandbox that forbids AF_UNIX reports seven Python and two Go live socket cases as skipped.
The standalone IPC runner must pass on a Linux executor with Unix sockets before Go opt-in.
Socket-free handler and bounded streaming tests are supplemental evidence. They do not verify peer UID enforcement.

### Optional container overlay

`deployment/docker_compose/docker-compose.orgmesh-history-go.yml` is an optional, manual overlay.
Its JSON syntax is valid YAML. Normal compose files do not reference it.
The Go container has no network, credentials, ports, environment file, or writable root filesystem.
Only Go can write the shared socket volume. The API mounts that volume read-only.
The current `Dockerfile.orgmesh-backend` explicitly runs as root, so the overlay uses API UID `0`.
Before use, check the running API UID. If it differs, do not use this overlay without reviewing ownership and peer UID.
The overlay does not change the API UID, security settings, or history-enabled flag.
Check the named volume directory owner and mode before enabling shadow mode.
No container build, startup, secret update, or production rollout is part of this patch.

Keep `python` for production until Linux IPC, real PostgreSQL, tenant middleware, live ACL, and browser tests pass.
Measure end-to-end p95 on the target hardware. The proposed regression limit is below 10%.
Synthetic projection and IPC measurements cannot establish SQL/ACL performance or a product speed gain.

### Synthetic benchmark

Run `python tools/benchmark_history_go.py --samples 1000 --output history-python.json` for Python projection only.
Add `--binary /tmp/orgmesh-historyd` for real IPC plus Python validation, CPU time, and combined RSS.
The IPC command fails when Unix sockets are unavailable. It does not silently substitute an IPC estimate.
Run `go test ./internal/history -run '^$' -bench BenchmarkProject -benchmem` for Go projection only.
Both use synthetic history sizes 100/1000/10000, page sizes 21/100, and concurrency 1/10/50.
The Go benchmark reports amortized operation time and allocation. It does not report request p50/p95.
The Python/IPC benchmark reports per-operation p50/p95. These are different measurements and cannot be directly compared.
No real SQL, ACL, database load, or production hardware is included.
