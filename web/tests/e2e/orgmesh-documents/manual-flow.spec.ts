import { test, expect } from "@playwright/test";
import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { WordDocumentPage } from "../pages/WordDocumentPage";

// Requires a running, authenticated stack and the staged production browser bundle.
test("Word tools → new → save → reopen → download → import @exclusive", async ({
  page,
}) => {
  test.skip(
    process.env.ORGMESH_WORD_E2E !== "true",
    "Enable the manual Word acceptance run explicitly"
  );
  const status = await page.request.get("/api/orgmesh/documents/status");
  expect(status.ok()).toBe(true);
  expect(await status.json()).toEqual({ enabled: true });
  const word = new WordDocumentPage(page);
  await word.tools();
  const id = await word.create(`Acceptance ${Date.now()}`);
  const text = "OrgMesh saved 中文 😀";
  await word.append(text);
  await word.save();
  await word.reopen(text);
  const download = await word.download();
  expect(download.suggestedFilename()).toMatch(/\.docx$/i);
  expect(await download.failure()).toBeNull();
  const path = await download.path();
  if (!path) throw new Error("Missing downloaded DOCX");
  const bytes = await readFile(path);
  const metadata = await page.request.get(`/api/orgmesh/documents/${id}`);
  const snapshot = await metadata.json();
  expect(createHash("sha256").update(bytes).digest("hex")).toBe(
    snapshot.content_hash
  );
  const content = await page.request.get(
    `/api/orgmesh/documents/${id}/versions/${snapshot.version_id}/content`
  );
  expect(await content.body()).toEqual(bytes);
  await word.tools();
  // The browser download has an opaque temporary name. Preserve its DOCX extension.
  const importedPath = test.info().outputPath("downloaded.docx");
  await download.saveAs(importedPath);
  await word.importFile(importedPath);
  await word.expectText(text);
});
