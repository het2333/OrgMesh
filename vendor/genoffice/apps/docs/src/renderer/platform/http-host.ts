import type { Lang } from '@genoffice/i18n'
import type { DocsHostPort, DocumentSnapshot, VersionResult } from './host'

const API = '/api/orgmesh/documents'
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

function snapshot(value: unknown, id: string): DocumentSnapshot {
  if (
    typeof value !== 'object' ||
    value === null ||
    !('document_id' in value) ||
    value.document_id !== id ||
    !('version_id' in value) ||
    typeof value.version_id !== 'string' ||
    !UUID.test(value.version_id) ||
    !('content_hash' in value) ||
    typeof value.content_hash !== 'string' ||
    !/^[a-f0-9]{64}$/.test(value.content_hash) ||
    !('title' in value) ||
    typeof value.title !== 'string' ||
    !('project_id' in value) ||
    value.project_id !== null
  )
    throw new Error('INVALID_DOCUMENT_RESPONSE')
  return {
    document_id: id,
    version_id: value.version_id,
    content_hash: value.content_hash,
    title: value.title,
    project_id: null,
  }
}

async function request(path: string, options: RequestInit = {}): Promise<Response> {
  const response = await fetch(`${API}${path}`, {
    ...options,
    credentials: 'same-origin',
    cache: 'no-store',
    redirect: 'error',
  })
  if (!response.ok) {
    if (response.status === 409) throw new Error('VERSION_CONFLICT')
    if (response.status === 401 || response.status === 403) throw new Error('AUTH_REQUIRED')
    if (response.status === 404) throw new Error('DOCUMENT_NOT_FOUND')
    throw new Error('DOCUMENT_REQUEST_FAILED')
  }
  return response
}

export function createHttpDocsHost(documentId: string, language: Lang): DocsHostPort {
  if (!UUID.test(documentId)) throw new Error('INVALID_DOCUMENT_ID')
  function boundId(id: string): string {
    if (id !== documentId) throw new Error('DOCUMENT_ID_MISMATCH')
    return `/${id}`
  }
  const unavailable = async (): Promise<never> => {
    throw new Error('NOT_ENABLED')
  }
  return {
    initialDocumentId: documentId,
    language,
    async openDocument(id) {
      return snapshot(await (await request(boundId(id))).json(), id)
    },
    async readVersion(id, versionId) {
      if (!UUID.test(versionId)) throw new Error('INVALID_VERSION_ID')
      return (await request(`${boundId(id)}/versions/${versionId}/content`)).arrayBuffer()
    },
    async saveVersion(id, expectedVersion, bytes, key): Promise<VersionResult> {
      const path = boundId(id)
      if (!UUID.test(expectedVersion)) throw new Error('INVALID_VERSION_ID')
      const form = new FormData()
      form.set('expected_version', expectedVersion)
      form.set(
        'file',
        new Blob([bytes], {
          type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        }),
        'document.docx',
      )
      const value: unknown = await (
        await request(`${path}/versions`, {
          method: 'POST',
          headers: { 'Idempotency-Key': key },
          body: form,
        })
      ).json()
      const saved = snapshot(value, id)
      if (
        typeof value !== 'object' ||
        value === null ||
        !('parent_version_id' in value) ||
        value.parent_version_id !== expectedVersion ||
        !('operation' in value) ||
        value.operation !== 'manual'
      )
        throw new Error('INVALID_DOCUMENT_RESPONSE')
      return { ...saved, parent_version_id: expectedVersion, operation: 'manual' }
    },
    startRun: unavailable,
    subscribeRun: () => {
      throw new Error('NOT_ENABLED')
    },
    cancelRun: unavailable,
    acceptProposal: unavailable,
    rejectProposal: unavailable,
    restoreVersion: unavailable,
  }
}
