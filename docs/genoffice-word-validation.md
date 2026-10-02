# GenOffice Word browser source checkpoint

Date: 2026-10-01 UTC

## Status

Task 1 is a source checkpoint. Gate A is blocked. This is not a completed Word integration.

The original audit used no deployment, push, production migration, model call, or new credential.
The user authorized publication of this source checkpoint on 2026-10-02. Acceptance limits remain unchanged.
No OrgMesh document API or menu entry is enabled. Tasks 2–8 remain unimplemented.

## Pinned sources

- OrgMesh: `ed2a2902278e1f96d2eaaaf9e68cc2b87b12638e`
- GenOffice: `676bf4d51239874d82d0d3edd10682c15ada367f`
- GenOffice source: https://github.com/genspark-ai/genoffice
- Prior history/Go patch SHA-256: `bdd828e382c19a4e26f381b5ad74ca3fb1e329c24ea1052bf0ea537bd0511429`

The original history worktree remains unchanged. Its staged patch matches the saved copy with fixed Git abbreviation length.
The new code lives in a separate worktree. The compatibility check uses a third temporary worktree.

## Included source

- Original GenOffice editor, toolbar, selection UI, and right panel
- Explicit `mountDocs(host)` and `window.orgmeshDocs.mount(host)` browser entry
- A bounded host contract with complete DOCX bytes and version identifiers
- Confirmed-load and save-lease guards
- ZIP inflation limits, hash checks, and rejection of unsafe package content
- Browser build, module-boundary check, unit tests, and Playwright fixture tests

The browser path does not create `window.desktop`, `projectApi`, or filesystem path aliases.
The original DOCX save pipeline remains in use. The implementation does not rebuild files from plain text.
AI submission and unsupported AutoSave stay disabled.

## Verified checks

- Upstream Docs TypeScript check: passed
- Upstream Docs tests: 329 files, 3,144 tests passed
- Checkpoint Docs tests: 331 files, 3,161 tests passed
- Focused host and original-renderer tests: 17 passed
- Docs and contract workspace TypeScript checks: passed
- Browser production build: passed
- Browser boundary check: passed; 506 modules retain the original editor, panel, schema, and save pipeline
- ESLint on new and changed TypeScript files: no errors; one unchanged upstream hook-dependency warning
- All original registry dependency versions and integrity values remain unchanged

The DOM test verifies the original fixture text before editing.
It saves Chinese text and emoji through the original pipeline, then checks the resulting DOCX XML.
It also checks that the original paragraphs remain present.

DOM tests do not prove browser layout, Word fidelity, or production API behavior.
The test environment supplies missing CSS/font APIs. It does not supply an Electron bridge.
Existing jsdom canvas and pseudo-element warnings remain visible in the test logs.
An initial full-suite run timed out in the existing password test. Its focused retry passed eight tests.
The final complete suite passed with bounded workers.

## Source review corrections

The source review found four important issues. Regression tests cover their corrections.

1. Failed browser loads cannot create a writable blank replacement
2. Save operations capture their host identity before asynchronous serialization
3. Browser spelling changes do not install desktop keyboard shields
4. The browser does not advertise unsupported AutoSave

The tests also found a late font-layout callback after disposal. The callback now checks disposal before accessing the editor.

## Browser gate: blocked

The two Playwright cases collect successfully. Neither reaches page assertions in this executor.
The installed Chromium process aborts when it creates a Unix socket: `Operation not permitted`.
The supported cloud browser returns `ERR_BLOCKED_BY_CLIENT` for the local renderer URL.
No restriction was bypassed. No server was used as a substitute test target.

The following remain unverified:

- Real browser open, edit, save, reopen, and download
- Original layout, selection highlight, and screenshots
- Browser handling of unsafe-document fixtures
- Full fidelity samples: styles, lists, tables, images, headers, footers, comments, revisions, and embedded fonts
- Production-build embedding and the remaining desktop-control audit

The included Playwright fixture serves the original source through Vite.
Production-build acceptance must also run before Gate A can pass.
Browser file upload and actual OrgMesh API wiring are not complete.

## Smallest next environment

Gate A needs an authorized test machine with:

- Node 22.12 or later and npm 10 or later
- The locked dependencies and a compatible Chromium installation
- Permission to create browser Unix sockets and use a local HTTP server
- Browser access to that local server

Gate A does not need model credentials, a paid model call, or a production server.
PostgreSQL, the document worker sandbox, and Onyx services become necessary for later gates.

## Reproduction

From `vendor/genoffice`:

```sh
npm ci --ignore-scripts --no-audit --no-fund
npm run typecheck -w @genoffice/docs
npm run typecheck -w @orgmesh/docs-runtime
npm run test -w @genoffice/docs -- --maxWorkers=4
npm run build:browser -w @genoffice/docs
```

From the OrgMesh root:

```sh
node tools/check_genoffice_browser_boundary.mjs
```

For the isolated browser fixture, from `web`:

```sh
NODE_PATH=../vendor/genoffice/node_modules \
  ../vendor/genoffice/node_modules/.bin/playwright test \
  --config playwright.genoffice.config.ts
```

Set `CHROMIUM_EXECUTABLE_PATH` only when using an existing compatible browser.
The fixture uses synthetic local document data. It does not call a model or the real document API.

## Compatibility checks

The prior history/Go patch and this source delta apply together at the pinned OrgMesh baseline.
The original staged patch is not committed or changed.

- Existing history Python fixture: 76 passed, 7 skipped
- Existing history React fixture: 16 passed
- Nine locale catalogs: 44 history keys and ICU arguments match
- Existing Go tests: passed, with two restricted Unix-socket tests skipped

These are focused fixture checks. They do not prove PostgreSQL migrations, live IPC, or production startup.
The full OrgMesh Python integration suite and web build/lint/type checks were not run.
This checkpoint does not modify their runtime paths.

## Next implementation boundary

Keep Gate A closed until browser and fidelity checks pass.
Then follow the approved plan: bounded candidate runtime, unique document writer, real manual-save gate, Onyx, and proposal UI.
Do not start model integration to work around an unverified editor or save path.

## Acceptance continuation: 2026-10-01 21:49 UTC

The current audit and exact remaining gates are in `genoffice-word-acceptance-matrix.md`.
Gate A remains blocked. The cloud Chromium UI confirms an extension-level localhost restriction.
Four more Task 1 source regressions were reproduced and fixed: file-drop navigation and three desktop-only controls.
This continuation adds no document API, candidate worker, or Onyx integration.
