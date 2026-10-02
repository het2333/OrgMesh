import { readFileSync, readdirSync } from 'node:fs'
import { resolve } from 'node:path'
import assert from 'node:assert/strict'
const directory = resolve('vendor/genoffice/apps/docs/out/browser')
const modules = JSON.parse(readFileSync(resolve(directory, 'browser-modules.json'), 'utf8'))
for (const suffix of ['/renderer/App.tsx', '/renderer/ai/AiPanel.tsx', '/renderer/editor/extensions.ts', '/renderer/file-actions.ts']) {
  assert(modules.some(name => name.endsWith(suffix)), `Missing original module: ${suffix}`)
}
assert(!modules.some(name => /(?:^|\/)node:|node_modules\/electron\/|__vite-browser-external/.test(name)), 'Node/Electron import reached the browser')
const page = readFileSync(resolve(directory, 'index.html'), 'utf8')
assert(page.includes("connect-src 'self'"), 'Missing same-origin network policy')
assert(page.includes("object-src 'none'"), 'Missing active object policy')
assert(!page.includes('genoffice-docx-media:'), 'Desktop byte transport remains in browser CSP')
const entry = page.match(/src="([^"]+\.js)"/)?.[1]
assert(entry, 'Missing browser entry')
const code = readFileSync(resolve(directory, entry.replace('/office/docs/', '')), 'utf8')
assert(/window\.orgmeshDocs=Object\.freeze\(\{mount:/.test(code), 'Browser entry lost its mount API')
console.log(`Browser boundary passed: ${modules.length} modules; original App, panel, schema, and save pipeline retained`)
