import { expect, type Page } from "@playwright/test";

export class OrgMeshAuditPage {
  constructor(readonly page: Page) {}
  async goto() {
    await this.page.goto("/admin/orgmesh-enterprise/audit");
    await expect(
      this.page.getByRole("button", { name: "Apply filters", exact: true }),
    ).toBeVisible();
  }
  async expectChange(before: number, after: number) {
    await expect(
      this.page.getByRole("list", { name: "OrgMesh audit", exact: true }),
    ).toContainText(`Versions ${before} → ${after}`);
    await expect(
      this.page.getByRole("list", { name: "OrgMesh audit", exact: true }),
    ).toContainText("Changed fields:");
    await expect(
      this.page.getByRole("list", { name: "OrgMesh audit", exact: true }),
    ).toContainText("Success");
    await expect(
      this.page.getByRole("list", { name: "OrgMesh audit", exact: true }),
    ).toContainText("Request ID:");
  }
  async setRange(start: string, end: string) {
    await this.page.getByLabel("Start (UTC)", { exact: true }).fill(start);
    await this.page.getByLabel("End (UTC)", { exact: true }).fill(end);
  }
  async apply() {
    await this.page
      .getByRole("button", { name: "Apply filters", exact: true })
      .click();
  }
  async expectRangeError() {
    await expect(
      this.page.getByRole("alert").filter({ hasText: "up to 90 days" }),
    ).toContainText("up to 90 days");
  }
  async selectAction(action: "Branding created" | "Branding updated") {
    await this.page
      .getByRole("combobox", { name: "Action", exact: true })
      .click();
    await this.page.getByRole("option", { name: action, exact: true }).click();
  }
  async selectSuccess() {
    await this.page
      .getByRole("combobox", { name: "Result", exact: true })
      .click();
    await this.page
      .getByRole("option", { name: "Success", exact: true })
      .click();
  }
}
