import { afterEach, describe, expect, it } from 'vitest'
import JSZip from 'jszip'
import { readFileSync } from 'node:fs'
import { webcrypto } from 'node:crypto'
import {
  installDocsHost,
  openHostedDocument,
  saveHostedDocument,
  getDocsHost,
  validateBrowserDocx,
  confirmHostedDocument,
  captureHostedSave,
} from '../src/renderer/platform/host'
import type { DocsHostPort, DocumentSnapshot, VersionResult } from '../src/renderer/platform/host'

Object.defineProperty(globalThis, 'crypto', { value: webcrypto, configurable: true })
const documentId = '10000000-0000-4000-8000-000000000001'
const versionId = '20000000-0000-4000-8000-000000000001'
const nextId = '20000000-0000-4000-8000-000000000002'
const fixture = new Uint8Array(readFileSync('../../fixtures/generated/simple.docx'))
const hash = async (bytes: Uint8Array) =>
  Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', new Uint8Array(bytes).buffer)))
    .map((x) => x.toString(16).padStart(2, '0'))
    .join('')
let dispose: (() => void) | undefined

afterEach(() => {
  dispose?.()
  dispose = undefined
})

async function makeHost() {
  const snapshot: DocumentSnapshot = {
    document_id: documentId,
    version_id: versionId,
    content_hash: await hash(fixture),
    title: 'Fixture.docx',
    project_id: null,
  }
  let saved: Uint8Array | null = null
  let expected: string | null = null
  const unsupported = async (): Promise<never> => {
    throw new Error('NOT_ENABLED')
  }
  const host: DocsHostPort = {
    initialDocumentId: documentId,
    language: 'en',
    openDocument: async () => snapshot,
    readVersion: async () => fixture.slice().buffer,
    saveVersion: async (_id, previous, bytes): Promise<VersionResult> => {
      expected = previous
      saved = new Uint8Array(bytes)
      return {
        ...snapshot,
        version_id: nextId,
        content_hash: await hash(saved),
        parent_version_id: previous,
        operation: 'manual',
      }
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
  return { host, snapshot, saved: () => saved, expected: () => expected }
}

describe('browser host boundary', () => {
  it('opens version bytes without creating an Electron bridge or a filesystem path', async () => {
    const { host } = await makeHost()
    dispose = installDocsHost(host)
    const opened = await openHostedDocument()
    expect(opened.path).toBeNull()
    expect(opened.bytes).toEqual(fixture)
    expect(window.desktop).toBeUndefined()
    expect(window.projectApi).toBeUndefined()
  })
  it('blocks save until the renderer confirms the loaded document', async () => {
    const { host } = await makeHost()
    dispose = installDocsHost(host)
    await openHostedDocument()
    await expect(saveHostedDocument(fixture.slice().buffer)).rejects.toThrow('DOCUMENT_NOT_OPEN')
  })
  it('sends the full DOCX and the confirmed version to the host', async () => {
    const fixtureHost = await makeHost()
    dispose = installDocsHost(fixtureHost.host)
    confirmHostedDocument((await openHostedDocument()).snapshot)
    const result = await saveHostedDocument(fixture.slice().buffer)
    expect(fixtureHost.saved()).toEqual(fixture)
    expect(fixtureHost.expected()).toBe(versionId)
    expect(result.version_id).toBe(nextId)
  })
  it('rejects bytes whose hash differs from the version', async () => {
    const { host, snapshot } = await makeHost()
    host.openDocument = async () => ({ ...snapshot, content_hash: '0'.repeat(64) })
    dispose = installDocsHost(host)
    await expect(openHostedDocument()).rejects.toThrow('CONTENT_HASH_MISMATCH')
  })
  it('does not advance the version after a failed save', async () => {
    const fixtureHost = await makeHost()
    const save = fixtureHost.host.saveVersion
    fixtureHost.host.saveVersion = async () => {
      throw new Error('VERSION_CONFLICT')
    }
    dispose = installDocsHost(fixtureHost.host)
    confirmHostedDocument((await openHostedDocument()).snapshot)
    await expect(saveHostedDocument(fixture.slice().buffer)).rejects.toThrow('VERSION_CONFLICT')
    fixtureHost.host.saveVersion = save
    await saveHostedDocument(fixture.slice().buffer)
    expect(fixtureHost.expected()).toBe(versionId)
  })
  it('does not adopt a save response after unmount', async () => {
    const { host } = await makeHost()
    let resolve!: (value: VersionResult) => void
    const pending = new Promise<VersionResult>((r) => {
      resolve = r
    })
    host.saveVersion = () => pending
    dispose = installDocsHost(host)
    const opened = await openHostedDocument()
    confirmHostedDocument(opened.snapshot)
    const saving = saveHostedDocument(fixture.slice().buffer)
    await new Promise((r) => setTimeout(r, 10))
    dispose()
    resolve({
      ...opened.snapshot,
      version_id: nextId,
      parent_version_id: versionId,
      operation: 'manual',
    })
    await expect(saving).rejects.toThrow('HOST_DISPOSED')
    expect(getDocsHost()).toBeNull()
  })
  it.each(['altChunk', 'externalImage', 'macro', 'doctype'])(
    'rejects unsafe %s documents before rendering',
    async (kind) => {
      const zip = await JSZip.loadAsync(fixture)
      if (kind === 'altChunk')
        zip.file('word/document.xml', '<w:document xmlns:w="urn:test"><w:altChunk/></w:document>')
      if (kind === 'externalImage')
        zip.file(
          'word/_rels/document.xml.rels',
          '<Relationships><Relationship TargetMode="External" Type="image" Target="https://external.invalid/image.png"/></Relationships>',
        )
      if (kind === 'macro') zip.file('word/vbaProject.bin', 'macro')
      if (kind === 'doctype')
        zip.file('word/document.xml', '<!DOCTYPE x [<!ENTITY x SYSTEM "file:///etc/passwd">]><x/>')
      await expect(
        validateBrowserDocx(await zip.generateAsync({ type: 'uint8array' })),
      ).rejects.toThrow()
    },
  )
  it('rejects uploads above 20 MiB', async () => {
    await expect(validateBrowserDocx(new Uint8Array(20 * 1024 * 1024 + 1))).rejects.toThrow(
      'DOCUMENT_TOO_LARGE',
    )
  })
})

it('does not send bytes from a disposed document to a new mounted host', async () => {
  const first = await makeHost()
  dispose = installDocsHost(first.host)
  confirmHostedDocument((await openHostedDocument()).snapshot)
  const lease = captureHostedSave()
  dispose()
  const second = await makeHost()
  dispose = installDocsHost(second.host)
  confirmHostedDocument((await openHostedDocument()).snapshot)
  await expect(lease!.save(fixture.slice().buffer)).rejects.toThrow('HOST_DISPOSED')
  expect(second.saved()).toBeNull()
})
