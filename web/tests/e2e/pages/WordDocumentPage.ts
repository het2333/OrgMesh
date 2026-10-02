import { expect, type Download, type Page } from "@playwright/test";

export class WordDocumentPage {
  constructor(private readonly page: Page) {}
  async tools() {
    await this.page.goto("/app/tools");
    await expect(this.page.getByTestId("Word/library")).toBeVisible();
  }
  async create(title: string) {
    await this.page.getByTestId("Word/name").fill(title);
    await this.page.getByTestId("Word/create").click();
    await expect(this.page).toHaveURL(/\/app\/tools\/documents\/[a-f0-9-]+$/);
    await this.expectEditor();
    return this.page.url().split("/").at(-1)!;
  }
  async importFile(path: string) {
    await this.page.getByTestId("Word/file").setInputFiles(path);
    await this.page.getByTestId("Word/create").click();
    await expect(this.page).toHaveURL(/\/app\/tools\/documents\/[a-f0-9-]+$/);
    await this.expectEditor();
  }
  private editor() {
    return this.page
      .frameLocator('[data-testid="Word/frame"]')
      .locator(".tiptap")
      .first();
  }
  async expectEditor() {
    await expect(this.editor()).toBeVisible();
    await expect(this.page.getByTestId("Word/save")).toBeEnabled();
  }
  async append(text: string) {
    const editor = this.editor();
    await editor.click();
    await editor.press("Control+End");
    await editor.press("Enter");
    await editor.pressSequentially(text);
    await expect(editor).toContainText(text);
  }
  async save() {
    const saved = this.page.waitForResponse(
      (response) =>
        response.request().method() === "POST" &&
        /\/api\/orgmesh\/documents\/[^/]+\/versions$/.test(response.url())
    );
    await this.page.getByTestId("Word/save").click();
    expect((await saved).ok()).toBe(true);
    await expect(this.page.getByTestId("Word/save")).toBeEnabled();
  }
  async reopen(text: string) {
    await this.page.reload();
    await this.expectText(text);
  }
  async expectText(text: string) {
    await this.expectEditor();
    await expect(this.editor()).toContainText(text);
  }
  async download(): Promise<Download> {
    const pending = this.page.waitForEvent("download");
    await this.page.getByTestId("Word/download").click();
    return pending;
  }
}
