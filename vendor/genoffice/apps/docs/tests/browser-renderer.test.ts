import { afterEach, beforeAll, expect, it, vi } from 'vitest'
import { act, createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { readFileSync } from 'node:fs'
import { webcrypto } from 'node:crypto'
import type { Editor } from '@tiptap/core'
import JSZip from 'jszip'
import { App } from '../src/renderer/App'
import { hasBrowserChanges, saveBrowserDocument } from '../src/renderer/platform/browser-session'
import { LocaleProvider } from '../src/renderer/i18n/locale'
import {
  installDocsHost,
  captureHostedSave,
  type DocsHostPort,
  type VersionResult,
} from '../src/renderer/platform/host'

let root: Root | undefined
let dispose: (() => void) | undefined
beforeAll(() => {
  Object.defineProperty(globalThis, 'crypto', { value: webcrypto, configurable: true })
  Object.defineProperty(globalThis, 'IS_REACT_ACT_ENVIRONMENT', { value: true, configurable: true })
  Object.defineProperty(document, 'fonts', {
    configurable: true,
    value: Object.assign(new EventTarget(), {
      status: 'loaded',
      ready: Promise.resolve(),
      check: () => true,
      load: async () => [],
      add: () => {},
      delete: () => true,
    }),
  })
  vi.stubGlobal('CSS', {
    escape: (value: string) => value.replace(/[^a-zA-Z0-9_-]/g, (character) => '\\' + character),
  })
  globalThis.ResizeObserver = class {
    observe() {}
    disconnect() {}
    unobserve() {}
  }
  window.matchMedia = (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener() {},
    removeListener() {},
    addEventListener() {},
    removeEventListener() {},
    dispatchEvent() {
      return false
    },
  })
  Element.prototype.scrollTo ??= () => {}
})
afterEach(async () => {
  if (root) await act(async () => root?.unmount())
  root = undefined
  dispose?.()
  document.body.innerHTML = ''
})

async function mountFixture(expectLoaded = true, blank = false, loseFirstResponse = false) {
  let bytes = new Uint8Array(
    readFileSync(
      blank ? 'tests/fixtures/orgmesh-blank.docx' : '../../fixtures/generated/simple.docx',
    ),
  )
  if (loseFirstResponse) {
    const zip = await JSZip.loadAsync(bytes)
    zip.file(
      'docProps/core.xml',
      '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dcterms="http://purl.org/dc/terms/"><dcterms:modified>2026-10-01T00:00:00Z</dcterms:modified><cp:revision>1</cp:revision></cp:coreProperties>',
    )
    bytes = new Uint8Array(await zip.generateAsync({ type: 'uint8array' }))
  }
  const hash = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes)))
    .map((x) => x.toString(16).padStart(2, '0'))
    .join('')
  let stored: ArrayBuffer | null = null
  let currentVersion = '20000000-0000-4000-8000-000000000001'
  const committed = new Map<string, VersionResult>()
  const attempts: Array<{ bytes: ArrayBuffer; key: string; expected: string }> = []
  const unsupported = async (): Promise<never> => {
    throw new Error('NOT_ENABLED')
  }
  const host: DocsHostPort = {
    initialDocumentId: '10000000-0000-4000-8000-000000000001',
    language: 'en',
    openDocument: async (id) => ({
      document_id: id,
      version_id: '20000000-0000-4000-8000-000000000001',
      content_hash: hash,
      title: 'Fixture.docx',
      project_id: null,
    }),
    readVersion: async () => bytes.buffer,
    saveVersion: async (id, expected, buffer, key) => {
      attempts.push({ bytes: buffer.slice(0), key, expected })
      const previous = committed.get(key)
      if (previous) return previous
      if (expected !== currentVersion) throw new Error('VERSION_CONFLICT')
      stored = buffer
      const savedHash = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', buffer)))
        .map((x) => x.toString(16).padStart(2, '0'))
        .join('')
      const result: VersionResult = {
        document_id: id,
        version_id: crypto.randomUUID(),
        parent_version_id: expected,
        content_hash: savedHash,
        title: 'Fixture.docx',
        project_id: null,
        operation: 'manual',
      }
      committed.set(key, result)
      currentVersion = result.version_id
      if (loseFirstResponse && committed.size === 1) throw new Error('RESPONSE_LOST')
      return result
    },
    startRun: unsupported,
    subscribeRun: () => {
      throw new Error('NOT_ENABLED')
    },
    cancelRun: unsupported,
    acceptProposal: unsupported,
    rejectProposal: unsupported,
    restoreVersion: unsupported,
  }
  dispose = installDocsHost(host)
  const container = document.createElement('div')
  document.body.append(container)
  root = createRoot(container)
  await act(async () => {
    root?.render(createElement(LocaleProvider, { initial: 'en', children: createElement(App) }))
  })
  if (expectLoaded) {
    await expect.poll(() => container.querySelector('.tiptap')).not.toBeNull()
    await expect.poll(() => container.querySelector('.ai-panel')).not.toBeNull()
    if (!blank) expect(container.querySelector('.tiptap')?.textContent).toContain('第一段。')
    await expect
      .poll(() => {
        try {
          return captureHostedSave() !== null
        } catch {
          return false
        }
      })
      .toBe(true)
  }
  return { container, stored: () => stored, committed, attempts }
}

it('opens the original editor and right panel with no Electron preload', async () => {
  const { container } = await mountFixture()
  expect(window.desktop).toBeUndefined()
  expect(
    container.querySelector<HTMLTextAreaElement>('.ai-input-box textarea')?.matches(':disabled'),
  ).toBe(true)
})

// This exercises the real editor/save pipeline in jsdom. It is not browser layout evidence.
it('saves CJK and emoji edits through the original full DOCX pipeline', async () => {
  const mounted = await mountFixture()
  const control = Reflect.get(window, '__aidocs') as {
    editor: Editor
    save(): Promise<boolean>
    getStatus(): string
  }
  await act(async () => {
    control.editor.commands.insertContentAt(1, '中文😀 round trip ')
  })
  let saved = false
  await act(async () => {
    saved = await control.save()
  })
  expect(saved, control.getStatus()).toBe(true)
  const bytes = mounted.stored()
  expect(bytes).not.toBeNull()
  const zip = await JSZip.loadAsync(bytes!)
  const xml = await zip.file('word/document.xml')!.async('string')
  expect(xml).toContain('中文😀 round trip ')
  expect(xml).toContain('第一段。')
  expect(xml).toContain('第二段。')
  expect(zip.file('[Content_Types].xml')).not.toBeNull()
  expect(window.desktop).toBeUndefined()
})

it('does not advertise unsupported browser AutoSave', async () => {
  const { container } = await mountFixture()
  expect(container.querySelector('.autosave-toggle')).toBeNull()
})

it('keeps browser typing live when spelling is toggled off and on', async () => {
  const { container } = await mountFixture()
  const errors: string[] = []
  const onError = (event: ErrorEvent) => {
    errors.push(event.message)
    event.preventDefault()
  }
  window.addEventListener('error', onError)
  try {
    const review = Array.from(container.querySelectorAll<HTMLButtonElement>('.ribbon-tab')).find(
      (button) => button.textContent === 'Review',
    )
    expect(review).toBeDefined()
    await act(async () => {
      review!.click()
    })
    const spelling = Array.from(container.querySelectorAll<HTMLButtonElement>('.rb-big')).find(
      (button) => button.textContent?.includes('Spelling'),
    )
    expect(spelling).toBeDefined()
    await act(async () => {
      spelling!.click()
    })
    await act(async () => {
      spelling!.click()
      await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()))
    })
    expect(errors).toEqual([])
    const event = new KeyboardEvent('keydown', { key: 'a', bubbles: true, cancelable: true })
    container.querySelector('.tiptap')!.dispatchEvent(event)
    expect(event.defaultPrevented).toBe(false)
  } finally {
    window.removeEventListener('error', onError)
  }
})

it('keeps renderer-rejected bytes non-writable instead of replacing them with blank content', async () => {
  const rejectStyle = vi.spyOn(CSS, 'escape').mockImplementationOnce(() => {
    throw new Error('fixture-renderer-rejected')
  })
  const { container, stored } = await mountFixture(false)
  await expect
    .poll(() => (Reflect.get(window, '__aidocs') as { getStatus(): string }).getStatus())
    .toContain('fixture-renderer-rejected')
  expect(container.querySelector('.ai-panel')).toBeNull()
  expect(() => captureHostedSave()).toThrow('DOCUMENT_NOT_OPEN')
  expect(stored()).toBeNull()
  rejectStyle.mockRestore()
})

it('blocks unsupported file drops on the browser AI panel without offering an attachment target', async () => {
  const { container } = await mountFixture()
  const panel = container.querySelector<HTMLElement>('.ai-panel')!
  const drag = new Event('dragover', { bubbles: true, cancelable: true })
  Object.defineProperty(drag, 'dataTransfer', { value: { types: ['Files'] } })
  await act(async () => {
    panel.dispatchEvent(drag)
  })
  expect(panel.classList.contains('ai-panel-dragover')).toBe(false)
  const drop = new Event('drop', { bubbles: true, cancelable: true })
  Object.defineProperty(drop, 'dataTransfer', {
    value: { files: [new File(['document'], 'attachment.docx')] },
  })
  await act(async () => {
    panel.dispatchEvent(drop)
  })
  expect(drop.defaultPrevented).toBe(true)
  expect(panel.classList.contains('ai-panel-dragover')).toBe(false)
  expect(window.desktop).toBeUndefined()
})

it.each([
  ['Insert', 'Picture'],
  ['Review', 'Protect Document'],
])('hides and disables the unsupported %s / %s desktop control', async (tab, label) => {
  const { container } = await mountFixture()
  const tabButton = Array.from(container.querySelectorAll<HTMLButtonElement>('.ribbon-tab')).find(
    (button) => button.textContent === tab,
  )
  expect(tabButton).toBeDefined()
  await act(async () => {
    tabButton!.click()
  })
  const control = Array.from(container.querySelectorAll<HTMLButtonElement>('.rb-big')).find(
    (button) => button.textContent === label,
  )
  expect(control).toBeDefined()
  expect(control!.disabled).toBe(true)
  expect(control!.hidden).toBe(true)
})

it('hides and disables the desktop picture replacement picker in browser mode', async () => {
  const { container } = await mountFixture()
  const { editor } = Reflect.get(window, '__aidocs') as { editor: Editor }
  await act(async () => {
    editor.commands.insertContentAt(0, {
      type: 'docProtected',
      attrs: {
        blockType: 'image',
        label: 'Picture',
        imageDataUrl: 'data:image/png;base64,iVBORw0KGgo=',
      },
    })
    editor.commands.setNodeSelection(0)
  })
  const tab = Array.from(container.querySelectorAll<HTMLButtonElement>('.ribbon-tab')).find(
    (button) => button.textContent === 'Picture Format',
  )
  expect(tab).toBeDefined()
  await act(async () => {
    tab!.click()
  })
  const control = Array.from(container.querySelectorAll<HTMLButtonElement>('.rb-big')).find(
    (button) => button.textContent === 'Replace Picture',
  )
  expect(control).toBeDefined()
  expect(control!.disabled).toBe(true)
  expect(control!.hidden).toBe(true)
})

it('opens the backend blank DOCX and saves a real document through the platform controls', async () => {
  const mounted = await mountFixture(true, true)
  const control = Reflect.get(window, '__aidocs') as { editor: Editor }
  await act(async () => {
    control.editor.commands.insertContentAt(1, '平台新建 中文😀')
  })
  expect(hasBrowserChanges()).toBe(true)
  const unload = new Event('beforeunload', { cancelable: true })
  expect(window.dispatchEvent(unload)).toBe(false)
  let saved = false
  await act(async () => {
    saved = await saveBrowserDocument()
  })
  expect(saved).toBe(true)
  expect(hasBrowserChanges()).toBe(false)
  const bytes = mounted.stored()
  expect(bytes).not.toBeNull()
  const zip = await JSZip.loadAsync(bytes!)
  expect(await zip.file('word/document.xml')!.async('string')).toContain('平台新建 中文😀')
  expect(window.dispatchEvent(new Event('beforeunload', { cancelable: true }))).toBe(true)
})

it.each([false, true])(
  'recovers a lost original-serializer save response (later edit: %s)',
  async (laterEdit) => {
    const mounted = await mountFixture(true, false, true)
    const control = Reflect.get(window, '__aidocs') as { editor: Editor }
    await act(async () => {
      control.editor.commands.insertContentAt(1, 'first saved edit ')
    })
    let first = true
    await act(async () => {
      first = await saveBrowserDocument()
    })
    expect(first).toBe(false)
    expect(mounted.committed.size).toBe(1)
    expect(hasBrowserChanges()).toBe(true)
    await new Promise((resolve) => setTimeout(resolve, 1100))
    if (laterEdit)
      await act(async () => {
        control.editor.commands.insertContentAt(1, 'newer local edit ')
      })
    let retried = false
    await act(async () => {
      retried = await saveBrowserDocument()
    })
    expect(retried).toBe(true)
    expect(mounted.attempts).toHaveLength(3)
    expect(mounted.attempts[1]?.key).toBe(mounted.attempts[0]?.key)
    expect(new Uint8Array(mounted.attempts[1]!.bytes)).toEqual(
      new Uint8Array(mounted.attempts[0]!.bytes),
    )
    expect(new Uint8Array(mounted.attempts[2]!.bytes)).not.toEqual(
      new Uint8Array(mounted.attempts[0]!.bytes),
    )
    expect(mounted.attempts[2]?.expected).toBe(
      mounted.committed.get(mounted.attempts[0]!.key)?.version_id,
    )
    expect(mounted.committed.size).toBe(2)
    expect(hasBrowserChanges()).toBe(false)
    const zip = await JSZip.loadAsync(mounted.stored()!)
    const xml = await zip.file('word/document.xml')!.async('string')
    expect(xml).toContain('first saved edit ')
    if (laterEdit) expect(xml).toContain('newer local edit ')
  },
)
