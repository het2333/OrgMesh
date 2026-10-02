import { expect, it, vi } from 'vitest'
import {
  bindBrowserSession,
  hasBrowserChanges,
  saveBrowserDocument,
} from '../src/renderer/platform/browser-session'

it('has no save action before the original editor is ready', async () => {
  expect(await saveBrowserDocument()).toBe(false)
  expect(hasBrowserChanges()).toBe(false)
})
it('uses live dirty state and drops actions when the editor unmounts', async () => {
  let dirty = true
  const save = vi.fn(async () => {
    dirty = false
    return true
  })
  const dispose = bindBrowserSession({ save, hasChanges: () => dirty })
  expect(hasBrowserChanges()).toBe(true)
  expect(await saveBrowserDocument()).toBe(true)
  expect(hasBrowserChanges()).toBe(false)
  dispose()
  expect(await saveBrowserDocument()).toBe(false)
  expect(save).toHaveBeenCalledTimes(1)
})
