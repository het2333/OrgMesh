import assert from "node:assert/strict";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import test from "node:test";
import { createRequire } from "node:module";
import { build } from "esbuild";

let rendering;
let directory;

test.before(async () => {
  directory = await mkdtemp(path.join(tmpdir(), "orgmesh-cjk-line-height-"));
  const entry = path.join(directory, "entry.ts");
  const output = path.join(directory, "rendering.cjs");
  await writeFile(entry, [
    `export { effectiveLineHeight } from ${JSON.stringify(path.resolve("components/slide-editor/text/text-line-height.ts"))};`,
    `export { rawRenderTextRuns, layoutRenderTextRuns, lineRenderHeight } from ${JSON.stringify(path.resolve("components/slide-editor/text/template-v2-text.ts"))};`,
    `export { templateV2UiToHtmlFragment } from ${JSON.stringify(path.resolve("lib/template-v2-json-to-html.ts"))};`,
    `import { StaticHtmlTextLayer } from ${JSON.stringify(path.resolve("components/slide-editor/text/StaticHtmlTextLayer.tsx"))};`,
    `import { createElement } from ${JSON.stringify(path.resolve("node_modules/react/index.js"))};`,
    `import { renderToStaticMarkup } from ${JSON.stringify(path.resolve("node_modules/react-dom/server.node.js"))};`,
    "export function renderStaticText(ui: unknown) { return renderToStaticMarkup(createElement(StaticHtmlTextLayer, { editingKey: null, nodeRefs: { current: new Map() }, revision: 0, ui })); }",
  ].join("\n"));
  await build({ entryPoints: [entry], outfile: output, bundle: true, platform: "node", format: "cjs", tsconfig: path.resolve("tsconfig.json"), logLevel: "silent" });
  rendering = createRequire(import.meta.url)(output);
});

test.after(async () => { await rm(directory, { recursive: true, force: true }); });

const title = {
  type: "text",
  size: { width: 500, height: 180 },
  font: { family: "Arial", size: 64, line_height: 0.8 },
  runs: [{ text: "OrgMesh\n平台演示", font: { line_height: 0.8 } }],
};

test("Chinese two-line titles use matching readable line heights in editor and export", () => {
  const lineHeight = rendering.effectiveLineHeight({ text: "OrgMesh\n平台演示", width: 500, fontSize: 64, lineHeight: 0.8, fallback: 1.15 });
  assert.equal(lineHeight, 1.1);
  const lines = rendering.layoutRenderTextRuns(rendering.rawRenderTextRuns(title), 500, "word");
  assert.equal(lines.length, 2);
  for (const line of lines) assert.equal(rendering.lineRenderHeight(line, lineHeight), 64 * 1.1);
  const html = rendering.templateV2UiToHtmlFragment({ elements: [title], components: [] });
  const cssLineHeights = Array.from(html.matchAll(/line-height:([\d.]+);/g), (match) => Number(match[1]));
  assert.ok(cssLineHeights.length >= 2);
  assert.ok(cssLineHeights.every((value) => value === lineHeight));
});

test("HTML text overlays clamp tight text styles and preserve normal math line height", () => {
  const mixedTitle = { ...title, runs: [...title.runs, { type: "latex", latex: "x^2", font: { line_height: 0.8 } }] };
  const html = rendering.renderStaticText({ elements: [mixedTitle], components: [] });
  assert.match(html, /line-height:70\.4px/);
  assert.match(html, /line-height:1\.1/);
  assert.doesNotMatch(html, /line-height:0\.8/);
  assert.match(html, /class="presenton-math"[^>]*line-height:normal/);
  const exported = rendering.templateV2UiToHtmlFragment({ elements: [mixedTitle], components: [] });
  assert.match(exported, /line-height:normal/);
});
