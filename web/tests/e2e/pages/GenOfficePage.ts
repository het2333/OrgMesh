import { expect, type Page, type Download } from '@playwright/test'
export class GenOfficePage {
  constructor(private readonly page: Page) {}
  async open(): Promise<void> { await this.page.goto('/office/docs/') }
  async expectOriginalEditor(): Promise<void> {
    await expect(this.page.locator('.tiptap').first()).toBeVisible()
    await expect(this.page.locator('.ribbon')).toBeVisible()
    await expect(this.page.locator('.ai-panel')).toBeVisible()
    await expect(this.page.locator('.ai-input-box textarea')).toBeDisabled()
    expect(await this.page.evaluate(() => 'desktop' in window)).toBe(false)
  }
  async appendText(text: string): Promise<void> {
    const editor = this.page.locator('.tiptap').first()
    await editor.click()
    await editor.press('Control+End')
    await editor.press('End')
    await editor.press('Enter')
    await editor.pressSequentially(text)
    await expect(editor).toContainText(text)
  }
  async save(): Promise<void> {
    await this.page.getByRole('button', { name: 'File', exact: true }).click()
    await this.page.getByRole('button', { name: /Save Ctrl\+S/ }).click()
    await expect(this.page.locator('html')).toHaveAttribute('data-saved-hash', /^[a-f0-9]{64}$/)
  }
  async reopenAndExpect(text: string): Promise<void> {
    await this.page.reload()
    await this.expectOriginalEditor()
    await expect(this.page.locator('.tiptap').first()).toContainText(text)
  }
  async download(): Promise<Download> {
    await this.page.getByRole('button', { name: 'File', exact: true }).click()
    const downloaded = this.page.waitForEvent('download')
    await this.page.getByRole('button', { name: /Save As/ }).click()
    return downloaded
  }
}
