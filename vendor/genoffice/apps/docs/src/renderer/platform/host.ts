import type { Lang } from '@genoffice/i18n'
import JSZip from 'jszip'
import { assertZipInflatesWithinLimits } from '@genoffice/zip-gate'
import type {
  CandidateInput,
  CandidateResult,
  DocumentSnapshot,
  ProposalState,
  RunEvent,
  RunRef,
  RunState,
  SelectionRef,
  VersionResult,
} from '@orgmesh/docs-runtime'
export type {
  CandidateInput,
  CandidateResult,
  DocumentSnapshot,
  ProposalState,
  RunEvent,
  RunRef,
  RunState,
  SelectionRef,
  VersionResult,
}

/** The embedding app supplies authority. This module never accepts filesystem paths or credentials. */
export interface DocsHostPort {
  readonly initialDocumentId: string
  readonly language?: Lang
  openDocument(id: string): Promise<DocumentSnapshot>
  readVersion(id: string, versionId: string): Promise<ArrayBuffer>
  saveVersion(
    id: string,
    expectedVersion: string,
    bytes: ArrayBuffer,
    idempotencyKey: string,
  ): Promise<VersionResult>
  startRun(
    id: string,
    selection: SelectionRef,
    instruction: string,
    idempotencyKey: string,
  ): Promise<RunRef>
  subscribeRun(runId: string, cursor: number, signal: AbortSignal): AsyncIterable<RunEvent>
  cancelRun(runId: string, key: string): Promise<RunState>
  acceptProposal(id: string, expectedVersion: string, key: string): Promise<VersionResult>
  rejectProposal(id: string, key: string): Promise<ProposalState>
  restoreVersion(id: string, expectedVersion: string, key: string): Promise<VersionResult>
}
export interface BrowserOpenResult {
  path: null
  encrypted?: false
  recovered?: false
  name: string
  hash: string
  bytes: Uint8Array
  snapshot: DocumentSnapshot
}
interface PendingWrite {
  snapshot: DocumentSnapshot
  bytes: ArrayBuffer
  hash: string
  key: string
}
interface Binding {
  host: DocsHostPort
  snapshot: DocumentSnapshot | null
  pending: DocumentSnapshot | null
  epoch: number
  pendingWrite: PendingWrite | null
}
let binding: Binding | null = null
let epoch = 0

export function getHostedSnapshot(): DocumentSnapshot | null {
  return binding?.snapshot ? { ...binding.snapshot } : null
}
export function getDocsHost(): DocsHostPort | null {
  return binding?.host ?? null
}
export function installDocsHost(host: DocsHostPort): () => void {
  if (binding) throw new Error('HOST_ALREADY_MOUNTED')
  const installed = {
    host,
    snapshot: null,
    pending: null,
    epoch: ++epoch,
    pendingWrite: null,
  }
  binding = installed
  return () => {
    if (binding === installed) {
      binding = null
      epoch++
    }
  }
}
function currentBinding(): Binding {
  if (!binding) throw new Error('HOST_NOT_MOUNTED')
  return binding
}
function assertCurrent(value: Binding): void {
  if (binding !== value || epoch !== value.epoch) throw new Error('HOST_DISPOSED')
}
async function contentHash(bytes: Uint8Array): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', new Uint8Array(bytes).buffer)
  return Array.from(new Uint8Array(digest), (x) => x.toString(16).padStart(2, '0')).join('')
}

/** Fail closed before the original renderer parses active or unsupported package parts. */
export async function validateBrowserDocx(bytes: Uint8Array): Promise<void> {
  if (bytes.byteLength > 20 * 1024 * 1024) throw new Error('DOCUMENT_TOO_LARGE')
  await assertZipInflatesWithinLimits(bytes, {
    maxParts: 10000,
    maxPartBytes: 100 * 1024 * 1024,
    maxTotalBytes: 100 * 1024 * 1024,
  })
  const zip = await JSZip.loadAsync(bytes)
  if (!zip.file('[Content_Types].xml') || !zip.file('word/document.xml'))
    throw new Error('INVALID_DOCX')
  for (const entry of Object.values(zip.files)) {
    const name = entry.unsafeOriginalName ?? entry.name
    if (
      name.startsWith('/') ||
      name.includes('\\') ||
      name.split('/').includes('..') ||
      /^[a-z]:/i.test(name)
    )
      throw new Error('UNSAFE_PART_PATH')
    if (/vbaProject|activeX|embeddings\//i.test(name)) throw new Error('UNSUPPORTED_ACTIVE_CONTENT')
    if (!/\.(xml|rels)$/i.test(name) || entry.dir) continue
    const xml = await entry.async('string')
    if (/<!DOCTYPE|<!ENTITY/i.test(xml)) throw new Error('UNSUPPORTED_XML_ENTITY')
    const parsed = new DOMParser().parseFromString(xml, 'application/xml')
    if (parsed.getElementsByTagName('parsererror').length) throw new Error('INVALID_XML')
    for (const node of Array.from(parsed.getElementsByTagName('*'))) {
      if (node.localName === 'altChunk') throw new Error('UNSUPPORTED_ALTCHUNK')
      if (
        node.localName === 'Relationship' &&
        node.getAttribute('TargetMode')?.toLowerCase() === 'external'
      )
        throw new Error('UNSUPPORTED_EXTERNAL_RELATIONSHIP')
      if (
        node.localName === 'Override' &&
        /macroEnabled/i.test(node.getAttribute('ContentType') ?? '')
      )
        throw new Error('UNSUPPORTED_ACTIVE_CONTENT')
    }
  }
}
export async function openHostedDocument(): Promise<BrowserOpenResult> {
  const active = currentBinding()
  active.snapshot = null
  active.pending = null
  active.pendingWrite = null
  const snapshot = await active.host.openDocument(active.host.initialDocumentId)
  assertCurrent(active)
  if (snapshot.document_id !== active.host.initialDocumentId)
    throw new Error('DOCUMENT_ID_MISMATCH')
  const bytes = new Uint8Array(
    await active.host.readVersion(snapshot.document_id, snapshot.version_id),
  )
  await validateBrowserDocx(bytes)
  if ((await contentHash(bytes)) !== snapshot.content_hash) throw new Error('CONTENT_HASH_MISMATCH')
  assertCurrent(active)
  active.pending = snapshot
  return { path: null, name: snapshot.title, hash: snapshot.content_hash, bytes, snapshot }
}
/** Only a successful original-renderer parse makes this version writable. */
export function confirmHostedDocument(snapshot: DocumentSnapshot): void {
  const active = currentBinding()
  if (active.pending !== snapshot) throw new Error('DOCUMENT_OPEN_SUPERSEDED')
  active.snapshot = snapshot
  active.pending = null
}
export interface HostedSaveLease {
  assertCurrent(): void
  settle(): Promise<VersionResult | null>
  save(buffer: ArrayBuffer): Promise<VersionResult>
}
/** Capture before waiting for content or serializing editor bytes. */
export function captureHostedSave(): HostedSaveLease | null {
  if (!binding) return null
  const active = binding
  if (!active.snapshot) throw new Error('DOCUMENT_NOT_OPEN')
  let previous: DocumentSnapshot = active.snapshot
  const check = () => {
    assertCurrent(active)
    if (active.snapshot !== previous) throw new Error('VERSION_CONFLICT')
  }
  async function settle(): Promise<VersionResult | null> {
    check()
    const pending = active.pendingWrite
    if (!pending) return null
    if (pending.snapshot !== previous) throw new Error('VERSION_CONFLICT')
    const result = await active.host.saveVersion(
      previous.document_id,
      previous.version_id,
      pending.bytes.slice(0),
      pending.key,
    )
    if (
      result.document_id !== previous.document_id ||
      result.parent_version_id !== previous.version_id
    )
      throw new Error('VERSION_RESPONSE_MISMATCH')
    if (pending.hash !== result.content_hash) throw new Error('CONTENT_HASH_MISMATCH')
    check()
    active.snapshot = result
    previous = result
    active.pendingWrite = null
    return result
  }
  return {
    assertCurrent: check,
    settle,
    async save(buffer) {
      // Resolve the original request before accepting any later editor state.
      // Serializers may change DOCX timestamps even when content did not change.
      const recovered = await settle()
      const bytes = new Uint8Array(buffer.slice(0))
      await validateBrowserDocx(bytes)
      check()
      const hash = await contentHash(bytes)
      if (recovered?.content_hash === hash) return recovered
      active.pendingWrite = {
        snapshot: previous,
        bytes: bytes.buffer,
        hash,
        key: crypto.randomUUID(),
      }
      const result = await settle()
      if (!result) throw new Error('DOCUMENT_SAVE_NOT_STARTED')
      return result
    },
  }
}
export async function saveHostedDocument(buffer: ArrayBuffer): Promise<VersionResult> {
  const lease = captureHostedSave()
  if (!lease) throw new Error('HOST_NOT_MOUNTED')
  return lease.save(buffer)
}
export function downloadDocx(buffer: ArrayBuffer, title: string): void {
  const url = URL.createObjectURL(
    new Blob([buffer], {
      type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    }),
  )
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = title.replace(/[\\/]/g, '_')
  anchor.click()
  setTimeout(() => URL.revokeObjectURL(url), 0)
}
