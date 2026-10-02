# GenOffice Docs host inventory

Pinned source: 676bf4d51239874d82d0d3edd10682c15ada367f.

## Adaptation scope

The browser host handles complete document bytes and version identifiers.
It does not create window.desktop, projectApi, or filesystem path aliases.
Desktop effects stop when the preload is absent. Native window, protection, Zotero, spelling-kick, AI, and AutoSave actions are guarded.
Some remaining desktop controls need browser UI acceptance before release.
AI composition remains disabled until the later Onyx phase passes its gates.

## Renderer call sites

- `apps/docs/src/renderer/App.tsx`: armContextMenu, claimContextMenu, confirmDocumentReplace, consumeAiDocContent, consumeHeadlessExport, consumeNewBlankDoc, consumePendingOpenDocx, fetchImage, getAiSettings, getRecentFiles, headlessExportDone, onCloseCheck, onCloseSaveRequest, onContextMenuRequest, onMenuCommand, onOpenDocx, onRenamedDocx, onTeardown, onViewImage, onZoteroRequest, openDocx, openDocxDecrypt, openDocxPath, reportCloseCheck, reportCloseSaveResult, reportViewMenuState, respondToZotero, saveImageAs, setDocPassword, spellDiag
- `apps/docs/src/renderer/ai/AiPanel.tsx`: addAttachmentPaths, addPastedImage, aiGskLogin, getPathForFile, pickAttachments, readAttachmentImage, setAiPanelPrefs
- `apps/docs/src/renderer/ai/files-skill.ts`: readAttachment
- `apps/docs/src/renderer/ai/tools.ts`: aiGenerateImage, analyzeMedia, createDocument, fetchImage, imageSearch, webSearch
- `apps/docs/src/renderer/ai/transport.ts`: aiStream, aiStreamCancel, onAiStream
- `apps/docs/src/renderer/components/ContextMenu.tsx`: onChromePressed, spellAddWord, spellIgnoreWord, spellLanguages, spellReplace, spellSetLanguages
- `apps/docs/src/renderer/components/PrintDialog.tsx`: print
- `apps/docs/src/renderer/components/Ribbon.tsx`: pickImage
- `apps/docs/src/renderer/components/ribbon-references-tab.tsx`: zoteroCommand
- `apps/docs/src/renderer/components/ribbon-tabs.tsx`: focusDocsTab, listDocsTabs, openNewTab, pickImage
- `apps/docs/src/renderer/editor/extensions.ts`: copyImageToClipboard
- `apps/docs/src/renderer/file-actions.ts`: discardDocPasswordIntents, docPasswordIntentRevision, exportHtml, exportPdf, getRecentFiles, getSystemLocale, pickExportImagesTarget, printPdfBuffer, saveDocx, saveDocxAs, saveDocxNew, saveDocxTo, saveMergedPdf, takeExportPdf, writeExportImage, writeRecoveryCopy
- `apps/docs/src/renderer/i18n/locale.tsx`: onLanguageChanged
- `apps/docs/src/renderer/main.tsx`: convertAltChunkHtml, getLanguage, getTheme, onAiPanelPrefsChanged, onThemeChanged
- `apps/docs/src/renderer/review-actions.ts`: openDocx
- `apps/docs/src/renderer/ui-theme.ts`: onThemeChanged

## Added boundary checks

- platform/host.ts: hash-bound open/save, bounded ZIP inflation, unsafe part rejection
- browser-main.tsx: mount the original App without preload
- system-fonts.ts: disable local font requests in browser mode
- i18n/locale.tsx: optional desktop language subscription
- components/Ribbon.tsx: browser-aware file actions
- components/ribbon-insert-tab.tsx: hide and disable the desktop image picker in browser mode
- components/ribbon-tabs.tsx: disable desktop window controls
- components/ribbon-references-tab.tsx: disable desktop Zotero actions
- components/ContextMenu.tsx: optional desktop spell actions

## Source provenance

The full locked upstream workspace is retained to preserve licenses and imports.
No Sheets, Slides, Shell, or shared UI source is changed.
Lifecycle install scripts are disabled.

## Validation boundary

Real browser acceptance remains blocked by this executor.
Shell Chromium cannot create its Unix socket (EPERM).
The supported cloud browser blocks the local renderer URL (ERR_BLOCKED_BY_CLIENT).
No server deployment or access-control bypass was attempted.

## Source review fixes

- Keep host bytes non-writable until the original renderer accepts the document.
- Reject a failed browser load without creating a blank replacement.
- Capture the host save lease before asynchronous serialization.
- Reject cross-mount writes before calling the host.
- Skip desktop spelling kicks before they install keyboard shields.
- Hide unsupported AutoSave.
- Ignore late font-layout callbacks after editor disposal.
- Block default file-drop navigation on the browser AI panel without showing a drop target.
- Hide and disable unsupported browser image insertion, image replacement, and document protection controls.

These checks pass in source tests. Real browser acceptance is still required.
