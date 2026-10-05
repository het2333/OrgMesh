# OrgMesh People verification

Date: 2026-10-03 UTC
Branch: `feat/glean-people`
Implementation base: `dd68931` (design), from main `624ecab`
Implementation checkpoint: `5e11e95`

## Result

The employee, team and reporting-relationship feature is implemented locally.
Full production acceptance has **not** passed. Do not merge or deploy on this report alone.
No remote push, deployment or production migration was performed.

## Implemented

- `/app/people` has employee, team and org-chart views using Opal and nine locale catalogs
- Name, enterprise email, department and job-title search; direct-department filters and bounded pagination
- Stable employee-ID links, selected profiles, team members and on-demand direct-report expansion
- URL-backed search, filters and selection; normal `/app/search?q=...` knowledge links
- Complete Feishu snapshot normalization with duplicate, malformed-membership, partial-crawl and department-cycle rejection
- One transaction for existing ACL memberships and new display metadata
- Read-only APIs use existing BASIC_ACCESS authentication and tenant-aware `get_session`
- All profile, list, team and relationship reads filter inactive, expired, missing and mismatched directory identities
- Native accounts disabled by an administrator remain disabled after sync
- Private fallback email remains an internal ACL identity. Only enterprise email is public contact/search data
- Missing fields stay missing. Production code contains no seed or demonstration employees

## Passed

- Snapshot, department-ancestor and migration tests: **19/19**
- Real query and router code in the isolated SQLite/API runner: **27/27**
- Official People component, SWR and ICU catalog tests: **18/18**
- Full official frontend Jest suite: **160 suites / 1361 tests passed**, with one unrelated failure listed below
- Changed Python files: Ruff lint and formatting checks passed
- Changed frontend files: formatting and targeted lint passed
- Full frontend lint: zero errors; 901 warnings remain in the existing repository
- Git whitespace checks passed

The isolated runner loads actual People ORM declarations, persistence/query code and router code.
It uses SQLite column variants and explicit test auth/session boundaries.
These results do not prove PostgreSQL, real tenant middleware or a deployed login flow.
Test data is synthetic and confined to test environments.

The privacy regression was observed failing before the fix.
Final tests cover private-email exclusion from snapshot display metadata, list, search, profile, team and relationship output.

## Failed or blocked

### Full frontend tests

One existing failure remains:

`src/lib/settings/hooks.test.tsx:65`

Test: `useSettings enterprise-settings 404 handling > a 404 yields default branding with no error and no retry`

Expected `Onyx`; current OrgMesh branding returns `OrgMesh`.
No People files failed in the full Jest run.

### Formal frontend type gate

`bun run types:check` failed with **14 diagnostics**, all outside the new People files:

- Four SWR mock errors at `src/sections/workspace/presentations/PresentationHistory.test.tsx:118,125,132,138`
  - The first three lack `isValidating`
  - The last lacks `error` and `isValidating`
- Two generated-route diagnostics for `app/app/agents/create/page`: editor props are not Next page props
- One generated-route diagnostic for `app/app/shared/[chatId]/page`: an extra exported function is rejected
- Seven generated-route diagnostics for `app/mcp/[[...path]]/route`: optional `params` conflicts with Next's required route context

The generated-route diagnostics appeared after the attempted production build generated route checks.
Their source files are unchanged by this feature. They were left unchanged deliberately.

### Production build

A complete webpack production build was attempted serially with output on independent tmpfs.

- 2 GiB Node heap: explicit JavaScript heap out-of-memory failure
- 3 GiB Node heap: SIGKILL during optimized compilation after 68.3 seconds
- Retry child maximum RSS: 3,967,944 KiB, approximately 3.78 GiB

The reason for the external SIGKILL was not independently established.
The build never reached a successful terminal result. No further heavy retry was made.
Root disk remained above 1 GiB free.

### Backend full environment

The standard backend test run and existing Feishu/access tests cannot collect because `fastapi_users` is missing.
PostgreSQL and Docker are unavailable in this execution environment.
PostgreSQL concurrency and live migration upgrade/downgrade remain unverified.
The additive migration was rendered as PostgreSQL SQL and upgraded/downgraded in disposable SQLite only.

### Browser and real data

The cloud browser request to the disposable local QA page returned `ERR_BLOCKED_BY_CLIENT`.
Inspection of the resulting error tab was rejected by the browser URL policy for the `chrome-error` protocol.
No alternate address or browser was used to bypass this restriction.

Actual browser screenshots, refresh, repeated clicks, keyboard behavior, narrow-screen layout and Back/Forward interaction are **not verified**.
Component tests of URL state are not a replacement for browser checks.
No static mockup or isolated bundle is presented as an actual browser screenshot.

Real enterprise Feishu data, company SSO and real cross-tenant middleware isolation were not tested.

## Migration boundary

`d83f0b6c1e92` follows the OrgMesh head `c71e9a2d4f60`.
The current source graph has one head, `d83f0b6c1e92`.
`c7bf5721733e` is an ancestor with successor `f1ca58b2f2ec`, not a separate head.
This was rechecked from all revision metadata during the 2026-10-05 publication review.
This change does not merge migration branches or apply a migration to production.

## Review and deferred minor

One independent whole-branch review found the private-email contact boundary issue.
It was fixed with failing-first regression tests and the related suites were rerun.

Deferred minor: People 404 routes use FastAPI `HTTPException` instead of the repository's `OnyxError` convention.
Their 404 behavior is tested. No unrelated error-wrapper change was made.

## Reproduction commands

In a complete repository environment:

```sh
PYTHONPATH=backend uv run pytest backend/tests/unit/onyx/access/test_people_directory.py backend/tests/unit/onyx/access/test_people_migration.py backend/tests/external_dependency_unit/orgmesh/test_people.py backend/tests/integration/tests/orgmesh/test_people_api.py -q
cd web
bun run test --runInBand
bun run lint
bun run types:check
bun run build
```

For explicit isolated verification with declared Python dependencies:

```sh
PYTHONPATH=backend python -m pytest --noconftest -c /dev/null -q backend/tests/unit/onyx/access/test_people_directory.py backend/tests/unit/onyx/access/test_people_migration.py backend/tests/unit/orgmesh/test_directory.py
python tools/test_people_isolated.py backend/tests/external_dependency_unit/orgmesh/test_people.py backend/tests/integration/tests/orgmesh/test_people_api.py
```

## Remaining acceptance work

1. Run the full backend/legacy ACL suite and migration tests on disposable PostgreSQL
2. Exercise real auth, tenant isolation and authorized Feishu sync in a test deployment
3. Resolve unrelated repository type/test failures under separate scope
4. Complete a production build in an environment with adequate resources
5. Run the required real browser flows and capture actual screenshots
6. Obtain explicit authorization before merge, push, deployment or production migration
