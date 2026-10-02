# Word manual flow source checkpoint

Date: 2026-10-02 UTC

## Scope

This change implements the manual part of the approved Word design:

1. Open the tools page.
2. Create a blank DOCX or import a DOCX file.
3. Edit with the original GenOffice Docs renderer.
4. Save the whole DOCX to private platform storage.
5. Reopen the saved document or download the committed DOCX.

The source is ready for review. The feature remains disabled by default.
This change does not deploy, enable, or migrate a running service.
AI actions, proposal review, and version-history controls remain disabled.
Onyx remains the main agent. Presenton and the Go history projection are unchanged.

## Data and access

- `ORGMESH_WORD_ENABLED=true` is required for document routes and the tools entry.
- Every operation uses the existing authenticated user and tenant-scoped database session.
- Each document belongs to one owner. A wrong-owner ID returns `NOT_FOUND`.
- Whole DOCX bytes are immutable. The database stores a current-version pointer and SHA-256 hash.
- Save compares `expected_version` while holding the document row lock.
- Create and save require a UUID `Idempotency-Key`. Same-key retries return the original result.
- A lost save response retains its exact bytes and key in the open editor.
- The next save settles that request before serializing the current editor state.
- Recovery can add a second, equivalent manual revision. It does not discard later edits.
- The editor download uses the exact committed version, even if another tab saves later.
- Stored bytes are checked after storage and before download. The browser checks the download hash too.
- `ORGMESH_WORD` files cannot use the generic chat-file route, even through a forged file reference.

The API includes status, list, create, metadata, version-content, and manual-save routes under `/orgmesh/documents`.
The browser calls them through `/api/orgmesh/documents`. No identity tokens cross frames.

## Input limits and UI guards

Uploads must be DOCX packages no larger than 20 MiB. Inflated content is limited to 100 MiB and 10,000 entries.
Validation rejects unsafe paths, encrypted entries, macros, active objects, external relationships, XML entities, and altChunk.
The service creates a real, deterministic blank DOCX. A shared fixture pins compatibility with the original editor.

The tools form blocks duplicate create clicks. It retains its request key after an uncertain response.
Changing accounts removes the previous owner's cached document list and pending navigation.
The editor warns before unloading or leaving through a link with unsaved changes.
A failed save keeps local edits. File → Save As remains a local-copy recovery path.
The platform Download button first saves, then fetches the exact stored version.

## Build and staging

The browser bundle uses `/office/docs/` as its asset base.
Generated files are ignored. They are not committed to the repository.

Build and stage only the browser bundle:

```sh
bash deployment/build_orgmesh_word.sh
```

Build the existing OrgMesh web image with the browser bundle:

```sh
ORGMESH_BUILD_WORD=true bash deployment/build_orgmesh_web.sh
```

The web staging script now copies `web/public` into the existing web image.
The Word build installs the pinned GenOffice dependencies with lifecycle scripts disabled.
It checks types and the browser boundary before copying assets.

For a memory-constrained build, set `NODE_OPTIONS=--max-old-space-size=640`.
Do not run the build and full Docs test suite together in a constrained executor.

The database migration is `c71e9a2d4f60`, after `b4c91a7e2d60`.
Apply it through the normal reviewed deployment process. No live migration was run here.
Enable the feature only after the browser and live-service gates below pass.

## Verification

Passed in this executor:

- 39 isolated FastAPI/SQLAlchemy tests, using real DOCX ZIP bytes and SQLite
- 16 platform API/component tests, with React and JSDOM
- Original-renderer tests for blank creation, CJK/emoji editing, and full-DOCX serialization
- Lost-response recovery with real serializer timestamps, with and without later local edits
- GenOffice Docs TypeScript check
- Production browser build, browser module boundary, and static-asset staging
- Nine locale catalogs: 25 Word keys and matching ICU arguments
- Focused Python Ruff/compile checks, frontend lint, shell syntax, and diff checks

The full Docs suite passed 334 files and 3,174 tests before the final retry correction.
After the retry correction, 17 save/open/dirty/browser test files passed all 117 tests.
JSDOM reports its existing unsupported canvas and pseudo-element warnings.
The isolated backend test environment reports one Starlette deprecation warning.
The build reports large existing editor chunks.

## Open acceptance gates

These checks did not pass or were not run:

- The real Chromium process cannot create its required Unix socket in this executor.
  Both existing browser-fixture cases stop before page assertions with `Operation not permitted`.
- The live platform flow was not run. No complete Onyx/PostgreSQL/object-store stack is available here.
- PostgreSQL row-lock concurrency, tenant schema routing, live authentication, and storage failures need live tests.
- The migration emits PostgreSQL SQL in tests, but it was not applied to a live database.
- Full web type checking/build is blocked by missing Next.js and other production dependencies in this checkout.
- Python static typing was not run. Installation of the optional checker was denied and was not retried.
- Full Word fidelity and real browser layout remain open, including headers, images, tables, and tracked changes.

The first production build and full-suite attempts ended with exit 137.
Resource pressure was suspected, but OOM was not confirmed.
The bounded build and one-worker full suite subsequently passed.
No browser or network restriction was bypassed.

## Live acceptance test

The new test uses real platform endpoints and the staged production bundle.
It creates, edits, saves, reloads, downloads, compares stored bytes, imports the download, and reopens it.
It does not mock the document API.

On an authorized test stack, use an existing authenticated test-user storage state:

```sh
cd web
ORGMESH_WORD_E2E=true \
ORGMESH_WORD_STORAGE_STATE=admin_auth.json \
bun run playwright --config playwright.word.config.ts
```

The test must pass before claiming the tools-to-download browser flow is accepted.
