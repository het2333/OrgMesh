import { test, expect } from '@playwright/test'
import { GenOfficePage } from '../pages/GenOfficePage'

test('opens_original_renderer_without_electron', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  const docs = new GenOfficePage(page)
  await docs.open()
  await docs.expectOriginalEditor()
  expect(errors).toEqual([])
  await page.screenshot({ path: 'output/playwright/genoffice-original-renderer.png', fullPage: true })
})
test('round_trips_docx_without_external_requests', async ({ page }) => {
  const requests: string[] = []
  const errors: string[] = []
  page.on('request', request => requests.push(request.url()))
  page.on('pageerror', error => errors.push(error.message))
  const docs = new GenOfficePage(page)
  await docs.open()
  await docs.appendText('中文 English 😀 saved in the original editor')
  await docs.save()
  await docs.reopenAndExpect('中文 English 😀 saved in the original editor')
  const download = await docs.download()
  expect(download.suggestedFilename()).toBe('Fixture.docx')
  expect(await download.failure()).toBeNull()
  expect(requests.filter(url => /^https?:/.test(url) && new URL(url).hostname !== '127.0.0.1')).toEqual([])
  expect(errors).toEqual([])
})
