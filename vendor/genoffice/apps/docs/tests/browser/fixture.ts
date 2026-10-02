import { mountDocs } from '../../src/renderer/browser-main'
import type { DocsHostPort, DocumentSnapshot } from '../../src/renderer/platform/host'
import fixtureUrl from '../../../../fixtures/generated/simple.docx?url'
const documentId = '10000000-0000-4000-8000-000000000001'
const storeKey = 'orgmesh-browser-fixture'
async function hash(bytes: Uint8Array): Promise<string> {
  return Array.from(
    new Uint8Array(await crypto.subtle.digest('SHA-256', new Uint8Array(bytes).buffer)),
    (x) => x.toString(16).padStart(2, '0'),
  ).join('')
}
const saved = sessionStorage.getItem(storeKey)
let bytes = saved
  ? Uint8Array.from(atob(saved), (c) => c.charCodeAt(0))
  : new Uint8Array(await (await fetch(fixtureUrl)).arrayBuffer())
let snapshot: DocumentSnapshot = {
  document_id: documentId,
  version_id: crypto.randomUUID(),
  content_hash: await hash(bytes),
  title: 'Fixture.docx',
  project_id: null,
}
const unsupported = async (): Promise<never> => {
  throw new Error('NOT_ENABLED')
}
const host: DocsHostPort = {
  initialDocumentId: documentId,
  language: 'en',
  openDocument: async () => snapshot,
  readVersion: async () => bytes.slice().buffer,
  saveVersion: async (_id, expected, buffer) => {
    if (expected !== snapshot.version_id) throw new Error('VERSION_CONFLICT')
    bytes = new Uint8Array(buffer)
    snapshot = { ...snapshot, version_id: crypto.randomUUID(), content_hash: await hash(bytes) }
    let encoded = ''
    for (const byte of bytes) encoded += String.fromCharCode(byte)
    sessionStorage.setItem(storeKey, btoa(encoded))
    document.documentElement.dataset.savedHash = snapshot.content_hash
    return { ...snapshot, parent_version_id: expected, operation: 'manual' }
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
await mountDocs(host)
