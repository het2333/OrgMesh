import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";
import { build } from "esbuild";

let integration;
let directory;

test.before(async () => {
  directory = await mkdtemp(path.join(tmpdir(), "orgmesh-presenton-prefix-"));
  const entry = path.join(directory, "entry.ts");
  const output = path.join(directory, "entry.mjs");
  await writeFile(entry, [
    `export * from ${JSON.stringify(path.resolve("lib/orgmesh-paths.ts"))};`,
    `export { getApiUrl, getFastAPIUrl, resolveBackendAssetUrl, normalizeBackendAssetUrls } from ${JSON.stringify(path.resolve("utils/api.ts"))};`,
    `export { SVG_UPDATE_ROUTE } from ${JSON.stringify(path.resolve("lib/svg-color.ts"))};`,
  ].join("\n"));
  await build({ entryPoints: [entry], outfile: output, bundle: true, platform: "node", format: "esm", tsconfig: path.resolve("tsconfig.json"), logLevel: "silent" });
  integration = await import(pathToFileURL(output).href);
  globalThis.window = {
    location: { origin: "https://orgmesh.example", search: "?fastapiUrl=https://untrusted.example" },
    env: { NEXT_PUBLIC_FAST_API: "http://private-engine:8000" },
  };
});

test.after(async () => {
  delete globalThis.window;
  await rm(directory, { recursive: true, force: true });
});

test("browser API and asset URLs use the authenticated same-origin prefix once", () => {
  assert.equal(integration.getApiUrl("/api/v1/ppt/presentation/deck"), "/presenton/api/v1/ppt/presentation/deck");
  assert.equal(integration.getApiUrl("/presenton/api/v1/ppt/presentation/deck"), "/presenton/api/v1/ppt/presentation/deck");
  assert.equal(integration.getApiUrl("/api/export-presentation"), "/presenton/api/export-presentation");
  assert.equal(integration.resolveBackendAssetUrl("/app_data/images/users/owner/photo.png?size=1"), "/presenton/app_data/images/users/owner/photo.png?size=1");
  assert.equal(integration.resolveBackendAssetUrl("/presenton/static/icons/x.svg"), "/presenton/static/icons/x.svg");
  assert.equal(integration.resolveBackendAssetUrl("https://orgmesh.example/app_data/images/x.png"), "/presenton/app_data/images/x.png");
  assert.equal(integration.resolveBackendAssetUrl("https://cdn.example/photo.png"), "https://cdn.example/photo.png");
  assert.equal(integration.resolveBackendAssetUrl("/vendor/fonts/example.ttf"), "/presenton/vendor/fonts/example.ttf");
  assert.deepEqual(integration.normalizeBackendAssetUrls({ fonts: { Example: "/vendor/fonts/example.ttf" } }), { fonts: { Example: "/presenton/vendor/fonts/example.ttf" } });
  assert.equal(integration.SVG_UPDATE_ROUTE, "/presenton/api/update-svg");
});

test("query overrides cannot send browser API traffic to another origin", () => {
  assert.equal(integration.getFastAPIUrl(), "https://orgmesh.example");
  assert.equal(integration.getApiUrl("/api/v2/templates"), "/presenton/api/v2/templates");
});

test("private export renderer base includes the prefix without duplication", () => {
  assert.equal(integration.getPresentonRenderBaseUrl("http://127.0.0.1:3000/"), "http://127.0.0.1:3000/presenton");
  assert.equal(integration.getPresentonRenderBaseUrl("http://127.0.0.1:3000/presenton/"), "http://127.0.0.1:3000/presenton");
});

test("editor and export renderer share prefixed endpoints and retain internal navigation", async () => {
  const header = await readFile("app/(presentation-generator)/presentation/components/PresentationHeader.tsx", "utf8");
  const renderer = await readFile("app/(export)/pdf-maker/PdfMakerPage.tsx", "utf8");
  const exporter = await readFile("app/api/export-presentation/route.ts", "utf8");
  const navigation = await readFile("app/(presentation-generator)/presentation/hooks/usePresentationNavigation.ts", "utf8");
  assert.match(header, /fetch\("\/presenton\/api\/export-presentation"/);
  assert.match(renderer, /fetch\(`\/presenton\/api\/export-presentation-data\//);
  assert.match(exporter, /return `\/presenton\/api\/export-presentation\/file\?/);
  assert.match(navigation, /router\.push\(\s*`\/presentation\?/);
  assert.doesNotMatch(header, /src="\/presenton\/logo-with-bg.png"/);
});
