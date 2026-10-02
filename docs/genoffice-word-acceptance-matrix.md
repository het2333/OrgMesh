# Word integration acceptance matrix

Audit date: 2026-10-01 UTC

## Release decision

**Blocked. Do not publish this checkpoint as a completed Word integration.**

Task 1 contains the browser host source. Gate A has not passed.
Tasks 2–8 remain unimplemented. Their absence is not a failed runtime test.
The approved plan stops backend and AI implementation until Gate A passes.
No remote write, deployment, model request, or production migration occurred in this audit.

## Source identity

- Word worktree: `feature/genoffice-word-integration`
- Word worktree base: `ed2a2902278e1f96d2eaaaf9e68cc2b87b12638e`
- Pinned GenOffice source: `676bf4d51239874d82d0d3edd10682c15ada367f`
- Prior cumulative source checkpoint: `a126e51ce3c8905aacf85e6959c82f9ac8776402`
- The publication continuation includes this audit delta and the prior cumulative source.

## Environment findings

Node 24.19.0 and npm 11.9.0 are installed. The locked vendored dependencies are present.
Bun, PostgreSQL tools, and Docker are absent from PATH. Their services were not tested.

The loopback Vite fixture started on `http://127.0.0.1:5178/office/docs/`.
Cloud Browser Use returned `net::ERR_BLOCKED_BY_CLIENT` before page assertions.
A full-desktop screenshot confirmed Chromium displays an extension-blocked page at that address.
Native text input also reported an unavailable AT-SPI provider.
Desktop screenshots work; the cloud computer is not wholly unavailable.
No browser security controls or network routes were changed.
The earlier local Chromium Unix-socket `EPERM` result remains historical evidence; it was not retried.

## Acceptance status

| Stage | Source state | Acceptance state | Required evidence still missing |
| --- | --- | --- | --- |
| 1: browser host | Implemented checkpoint; four more guard regressions fixed | Gate A blocked | Real-browser open/edit/save/reopen/download; original layout and selection; unsafe fixture requests; production bundle embedding; full DOCX fidelity |
| 2: candidate runtime | Contracts only | Not implemented or run | Version-bound selection; safe DOCX rewrite; unchanged parts; Unicode/limits; bounded isolated worker |
| 3: document writer | Absent | Not implemented or run | PostgreSQL owner/tenant checks; real concurrent CAS; idempotency; immutable object commit; safe restore |
| 4: real browser host/API | Absent | Gate B not reached | Manual save/reopen/download through real APIs; conflict preservation; owner/document/BFCache cleanup |
| 5: Onyx runtime | Absent | Not implemented or run | Main-agent tool allowlist; persistent event replay; cancel/deadline fences; recovery without repeated model calls |
| 6: proposals and undo | Absent | Not implemented or run | Context/selection capture; preview; accept/reject; generation/version fences; safe undo; IME and switched-document races |
| 7: isolation and recovery | Absent | Not implemented or run | Cross-owner/tenant denial; hostile DOCX; worker network/RSS/time enforcement; expiry and failure recovery |
| 8: end-to-end and compatibility | Incomplete | Not run on final product | Full workflow and races through browser/API; final compatibility checks; one authorized model smoke; independent whole-branch review |

A passing build or jsdom test does not satisfy either browser gate.
Fixed fixture responses do not prove real API, PostgreSQL, worker isolation, or model integration.
The existing browser test fixture uses local synthetic storage; it is not the document API.

## Small Task 1 fixes

All four new cases first failed against the existing source:

1. A file drop on the browser AI panel did not cancel default navigation
2. The unsupported Picture picker remained enabled and visible
3. The unsupported Replace Picture picker remained enabled and visible
4. The hidden Protect Document control remained enabled

The fixes cancel browser panel drops and gate those controls.
The source-only patch applies cleanly to cumulative checkpoint `a126e51` with `git apply --check`.
The desktop attachment handler and picker behavior retain their previous branches.
No new editor, backend, model adapter, or dependency was added.

## Source checks in this audit

- Focused browser-host and original-renderer tests: 2 files, 21 tests passed with one worker
- Docs and contract workspace TypeScript checks: passed
- Browser production build: passed; 549 modules transformed
- Built browser boundary: passed; 506 bundled modules retain the original editor, panel, schema, and save pipeline
- Changed TypeScript files: Prettier and ESLint passed
- Whitespace check: passed
- Existing Playwright fixture: both tests collected with `--list`; browser assertions were not run
- Full Docs suite, first attempt: failed with one unexpected worker exit; 330/331 files and 3162/3165 tests passed
- Concurrent focused attempt: killed with exit 137; the serial focused retry above passed
- Full Docs suite, single-worker retry: passed; 331 files and 3165 tests in 425.35 seconds

The test logs include existing jsdom canvas and pseudo-element warnings.
The build reports a large-chunk warning. Neither warning is real-browser evidence.
The original audit recorded only an author review. The publication review below covers the later source delta.

## Commands and evidence

Run these source checks from `vendor/genoffice`:

```sh
npm run test -w @genoffice/docs -- browser-host.test.ts browser-renderer.test.ts --maxWorkers=1
npm run test -w @genoffice/docs -- --maxWorkers=1
npm run typecheck -w @genoffice/docs
npm run typecheck -w @orgmesh/docs-runtime
npm run build:browser -w @genoffice/docs
./node_modules/.bin/prettier --check apps/docs/src/renderer/ai/AiPanel.tsx apps/docs/src/renderer/components/Ribbon.tsx apps/docs/src/renderer/components/ribbon-insert-tab.tsx apps/docs/src/renderer/components/ribbon-tabs.tsx apps/docs/tests/browser-renderer.test.ts
./node_modules/.bin/eslint apps/docs/src/renderer/ai/AiPanel.tsx apps/docs/src/renderer/components/Ribbon.tsx apps/docs/src/renderer/components/ribbon-insert-tab.tsx apps/docs/src/renderer/components/ribbon-tabs.tsx apps/docs/tests/browser-renderer.test.ts
```

Run the boundary and whitespace checks from the OrgMesh root:

```sh
node tools/check_genoffice_browser_boundary.mjs
git diff --check
```

For the existing real-browser fixture, run from `web` in a permitted test environment:

```sh
NODE_PATH=../vendor/genoffice/node_modules \
  ../vendor/genoffice/node_modules/.bin/playwright test \
  --config playwright.genoffice.config.ts
```

The current fixture has two cases. It does not yet cover the entire Gate A matrix.
Add production-build embedding and fidelity/unsafe-fixture cases before claiming Gate A passes.
Preserve screenshots, downloaded DOCX bytes, console errors, and request evidence.
Do not replace browser evidence with Node or jsdom results.

## Required Gate A fixture matrix

- Open the unchanged original editor, toolbar, selection UI, and right AI panel without Electron
- Edit Chinese, English, emoji, and composed input; save; reload; verify persisted text; download
- Verify styles, numbering, tables, images, headers, footers, comments, revisions, and embedded fonts
- Compare untouched DOCX semantics and resource hashes; do not compare ZIP bytes as semantic equality
- Reject altChunk, external image relationships, active content, unsafe paths, and XML entities before use
- Record that no external document-resource request or local-font permission request occurs
- Verify unsupported desktop controls are hidden and disabled in the real browser
- Load the production bundle through the same-origin embedding contract and repeat the basic round trip

## Next environment and stopping condition

Resume Gate A on an authorized machine with Chromium, local HTTP access, and browser Unix-socket support.
It needs no model credentials or production server.
After Gate A passes, follow Tasks 2–8 in the approved order.
Later gates require PostgreSQL, Onyx services, and the isolated Node worker runtime.
Release acceptance remains blocked until every required gate passes.
The user authorized publication of the current source checkpoint on 2026-10-02.
This authorization does not mark any acceptance gate as passed.

## Publication review: 2026-10-02 UTC

The user authorized publication of the current source checkpoint to the default branch.
The README and commit state that Word Task 1 is incomplete and Tasks 2–8 are unimplemented.
Gate A remains blocked; source publication does not change the acceptance decision.

An independent review found that author CSS could override hidden ribbon controls.
The source now applies `display: none` to `.rb-big[hidden]`.
A CSSOM regression test failed before this rule and passes after it.
The file-drop test also checks the drag highlight before drop clears it.
JSDOM computed style alone did not reproduce the CSS cascade issue.
Real-browser visibility remains part of Gate A.
The independent reviewer rechecked both corrections and found no remaining substantive issue in this delta.

Fresh publication checks:

- Three focused browser test files: 22 tests passed
- Browser production build: passed
- Browser boundary: passed; 506 modules preserve the original editor and save path
- Changed source formatting, ESLint, and whitespace checks: passed

The first publication attempts encountered worker termination and exit 137.
A 768 MiB TypeScript heap was too small. A bounded 1,280 MiB retry passed before the final CSS test was added.
Final checks after that addition are recorded in the progress checkpoint.

Final publication-source verification:

- Full Docs suite: 332 test files and 3,166 tests passed
- Focused browser suite: 3 files and 22 tests passed
- Final Docs TypeScript check: passed with a bounded 1,024 MiB heap
- Document runtime contract TypeScript check: passed
- Browser production build and 506-module boundary check: passed
- Changed source formatting, ESLint, and whitespace checks: passed
- Independent review: both findings corrected and rechecked; no remaining substantive delta issue

The initial worker failures and heap limits are environment failures, not passing test results.
The final serial checks above supersede those failed attempts for this source.
Real-browser Gate A and production acceptance remain unverified.
