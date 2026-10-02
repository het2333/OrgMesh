/** Stage only the verified browser output. Never copy desktop code or credentials. */
import { cpSync, existsSync, mkdirSync, readFileSync, rmSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const source = resolve(root, 'vendor/genoffice/apps/docs/out/browser')
const target = resolve(root, 'web/public/office/docs')
if (!existsSync(resolve(source, 'index.html'))) throw new Error('Build the Word browser entry first')
const html = readFileSync(resolve(source, 'index.html'), 'utf8')
if (!html.includes('/office/docs/assets/')) throw new Error('Unexpected browser asset base')
mkdirSync(dirname(target), { recursive: true })
rmSync(target, { recursive: true, force: true })
cpSync(source, target, { recursive: true, filter: path => !path.endsWith('browser-modules.json') })
console.log('Staged Word browser assets at web/public/office/docs')
