import react from '@vitejs/plugin-react'
import { builtinModules } from 'node:module'
import { resolve } from 'node:path'
import { defineConfig } from 'vite'
const builtins = new Set([...builtinModules, ...builtinModules.map((name) => `node:${name}`)])
export default defineConfig({
  root: 'src/renderer',
  base: '/office/docs/',
  plugins: [
    react(),
    {
      name: 'orgmesh-browser-boundary',
      enforce: 'pre',
      resolveId(source) {
        if (builtins.has(source) || source === 'electron')
          throw new Error(`Forbidden browser import: ${source}`)
      },
    },
    {
      name: 'orgmesh-browser-manifest',
      enforce: 'post',
      generateBundle(_options, bundle) {
        const modules = Object.values(bundle).flatMap((item) =>
          item.type === 'chunk' ? Object.keys(item.modules) : [],
        )
        this.emitFile({
          type: 'asset',
          fileName: 'browser-modules.json',
          source: JSON.stringify(modules, null, 2),
        })
        const page = bundle['browser.html']
        if (page) {
          delete bundle['browser.html']
          page.fileName = 'index.html'
          bundle['index.html'] = page
        }
      },
    },
  ],
  build: {
    outDir: '../../out/browser',
    emptyOutDir: true,
    rollupOptions: {
      preserveEntrySignatures: 'strict',
      input: resolve(__dirname, 'src/renderer/browser.html'),
    },
  },
})
