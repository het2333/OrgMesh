# OrgMesh frontend recovery verification

Date: 2026-10-04 UTC

## Scope

This change repairs the approved frontend blockers on `recovery/people-20261003`.
The source baseline is `7e13ef4ffc656b06d5d1eeaf4ab6a1280620835c`.
The six recovered People commits and the work-email privacy fix remain in place.

## Changes

- Declare the date-range picker and toast hook store as client modules.
- Wrap the agent editor in a page component with valid Next page props.
- Keep the shared-chat helper private to its page module.
- Require the MCP route context promise. Its catch-all path stays optional.
- Complete the SWR mock response fields in presentation history tests.
- Expect the existing OrgMesh default brand in the settings test.
- Skip the Sentry build plugin when its token or DSN is absent.
- Disable build telemetry, source uploads, and release creation and finalization.

Runtime Sentry error reporting still depends on the DSN in the separate instrumentation files.
This change does not claim that runtime reporting is disabled for a configured production service.
The verification commands cleared the DSN and token and disabled Next telemetry.
The Sentry regression tests verify configuration decisions through mocked plugin boundaries.
They do not prove network isolation for a configured production service.

## Regression evidence

The actual Next SWC server transform rejected both hook modules before the fix.
The transform now emits their client-entry boundaries. Both regression cases pass.
The date-range component's six existing interaction tests also pass.

The branding test failed with expected `Onyx` and actual `OrgMesh` before the correction.
The current product settings and People design specify OrgMesh branding.

The formal type check first reproduced four incomplete SWR response errors.
The installed Next webpack guard generator then reproduced the remaining ten route errors.
Those generated checks were included in the final formal type check.
No compiler errors were hidden or ignored.

## Passed checks

- `bun run types:check`: zero errors; type coverage 98.91% across 1,280 files
- Full frontend Jest: 163 suites and 1,366 tests passed
- `bun run lint`: zero errors; 901 existing warnings
- Formatting: all ten changed frontend files passed
- Python Ruff: the People snapshot, query, route, migration, and test files passed
- People snapshot and disposable migration tests: 16 passed
- Isolated real People persistence, query, and route tests: 27 passed
- Git whitespace checks passed

The 43 backend checks use isolated boundaries and SQLite where stated in their test tools.
They do not prove deployed authentication, tenant middleware, PostgreSQL locking, or live Feishu access.

## Incomplete production build

The full webpack build used a 3 GiB Node heap after the TTS workload stopped.
It entered optimized compilation. Reading the running session returned this tool error:

`write_stdin(session_id=13170): automatic approval review was cancelled`

No terminal build exit code was recorded. The last diagnostics show the `compile` stage.
No `BUILD_ID` or standalone server artifact exists.
A read-only check found no visible Next process and a free build file lock.
The cancellation cause remains unverified. This is not a successful build or a confirmed OOM.
The build was not restarted after that error.

## Blocked browser and live-service checks

The actual Next development server reported ready at `http://127.0.0.1:3021`.
The cloud browser opened the original People URL:

`http://127.0.0.1:3021/app/people`

It returned `net::ERR_BLOCKED_BY_CLIENT` again. The client blocking cause remains unverified.
No alternate URL, port, or browser was used. The temporary development server exited with code 130.
The browser did not display the application. No application screenshot is an acceptance result.
Refresh, repeated clicks, keyboard use, narrow screens, and Back/Forward remain unverified.

The standard backend tests stopped during collection because `fastapi_users` is absent.
No PostgreSQL or Docker executable was found. Full backend dependencies were not restored.
Real login, tenant isolation, production migrations, and enterprise Feishu data remain unverified.

## Word source boundary

The cloud source contains the manual Word document router and browser HTTP host.
It supports private create, import, save, reopen, and download operations behind the existing feature gate.
The feature is disabled by default.
The HTTP host's run, proposal, and restore operations still raise `NOT_ENABLED`.
The Onyx AI edit workflow is not connected in this verified source.

## Remaining gates

1. Finish a production build after the session cancellation cause is resolved
2. Verify the real application in an allowed cloud browser session
3. Run authenticated PostgreSQL and tenant tests against the full service environment
4. Verify a real Feishu snapshot with approved enterprise access

This work does not merge, push, deploy, or migrate a production service.
