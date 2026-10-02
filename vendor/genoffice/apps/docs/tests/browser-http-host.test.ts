import { afterEach, expect, it, vi } from 'vitest'
import { createHttpDocsHost } from '../src/renderer/platform/http-host'

const id = '10000000-0000-4000-8000-000000000001'
const version = '20000000-0000-4000-8000-000000000001'
const snapshot = {
  document_id: id,
  version_id: version,
  content_hash: 'a'.repeat(64),
  title: 'Saved.docx',
  project_id: null,
}
afterEach(() => vi.unstubAllGlobals())

it('uses only same-origin authenticated document endpoints', async () => {
  const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify(snapshot)))
  vi.stubGlobal('fetch', fetcher)
  const host = createHttpDocsHost(id, 'zh')
  expect(await host.openDocument(id)).toEqual(snapshot)
  expect(fetcher).toHaveBeenCalledWith(
    `/api/orgmesh/documents/${id}`,
    expect.objectContaining({ credentials: 'same-origin', cache: 'no-store' }),
  )
  expect(host.language).toBe('zh')
  await expect(host.openDocument('../other')).rejects.toThrow('DOCUMENT_ID_MISMATCH')
  expect(fetcher).toHaveBeenCalledTimes(1)
})

it('sends full bytes, expected version and stable request key on save', async () => {
  const result = {
    ...snapshot,
    version_id: '30000000-0000-4000-8000-000000000001',
    parent_version_id: version,
    operation: 'manual',
  }
  const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify(result)))
  vi.stubGlobal('fetch', fetcher)
  const host = createHttpDocsHost(id, 'en')
  expect(await host.saveVersion(id, version, new Uint8Array([1, 2]).buffer, 'request-key')).toEqual(
    result,
  )
  const [url, options] = fetcher.mock.calls[0]!
  expect(url).toBe(`/api/orgmesh/documents/${id}/versions`)
  expect(options.headers['Idempotency-Key']).toBe('request-key')
  expect(options.body.get('expected_version')).toBe(version)
  expect(options.body.get('file').size).toBe(2)
})

it('never retries conflict responses or starts AI', async () => {
  const fetcher = vi
    .fn()
    .mockResolvedValue(new Response(JSON.stringify({ error_code: 'CONFLICT' }), { status: 409 }))
  vi.stubGlobal('fetch', fetcher)
  const host = createHttpDocsHost(id, 'en')
  await expect(host.saveVersion(id, version, new ArrayBuffer(0), 'key')).rejects.toThrow(
    'VERSION_CONFLICT',
  )
  await expect(host.startRun(id, {} as never, '', 'key')).rejects.toThrow('NOT_ENABLED')
  expect(fetcher).toHaveBeenCalledTimes(1)
})

it('rejects a successful response with another document identity', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue(new Response(JSON.stringify({ ...snapshot, document_id: version }))),
  )
  await expect(createHttpDocsHost(id, 'en').openDocument(id)).rejects.toThrow(
    'INVALID_DOCUMENT_RESPONSE',
  )
})
