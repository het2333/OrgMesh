import { expect, type Page } from "@playwright/test";
import { randomUUID } from "node:crypto";
import type {
  BrandingView,
  BrandingPatch,
} from "@/lib/orgmesh-enterprise/types";

const API = "/api/orgmesh-enterprise/v1";

export class OrgMeshBrandingPage {
  constructor(readonly page: Page) {}

  async requireIsolatedEnabledService() {
    const base = new URL(process.env.BASE_URL || "http://localhost:3000");
    expect(["localhost", "127.0.0.1", "[::1]"]).toContain(base.hostname);
    const response = await this.page.request.get(`${API}/capabilities`);
    expect(
      response.ok(),
      "Start the isolated app and private service with branding and audit enabled.",
    ).toBeTruthy();
    expect(await response.json()).toMatchObject({
      branding_enabled: true,
      audit_enabled: true,
    });
  }

  async goto() {
    await this.page.goto("/admin/orgmesh-enterprise/branding");
    await expect(
      this.page.getByRole("textbox", { name: "Application name", exact: true }),
    ).toBeVisible();
  }

  async current(): Promise<BrandingView> {
    const response = await this.page.request.get(`${API}/branding`);
    expect(response.ok()).toBeTruthy();
    return response.json();
  }

  async externalSave(patch: BrandingPatch): Promise<BrandingView> {
    const response = await this.page.request.patch(`${API}/branding`, {
      data: patch,
      headers: { "Idempotency-Key": randomUUID() },
    });
    expect(response.ok()).toBeTruthy();
    return response.json();
  }

  async restore(original: BrandingView) {
    const current = await this.current();
    if (
      current.name !== original.name ||
      current.greeting !== original.greeting
    ) {
      await this.externalSave({
        name: original.name,
        greeting: original.greeting,
        logo_asset_id: original.logo_asset_id,
        expected_version: current.version,
      });
    }
  }

  async fill(name: string, greeting: string) {
    await this.page
      .getByRole("textbox", { name: "Application name", exact: true })
      .fill(name);
    await this.page
      .getByRole("textbox", { name: "Greeting", exact: true })
      .fill(greeting);
  }

  async save(duplicate = false) {
    const save = this.page.getByRole("button", { name: "Save", exact: true });
    if (duplicate) await save.dblclick();
    else await save.click();
  }

  async expectSaved() {
    await expect(this.page.getByRole("status")).toContainText(
      "Branding saved.",
    );
  }
  async expectConflict() {
    await expect(
      this.page
        .getByRole("alert")
        .filter({ hasText: "Another administrator changed" }),
    ).toContainText("Another administrator changed");
  }
  async expectUnavailable() {
    await expect(
      this.page
        .getByRole("alert")
        .filter({ hasText: "Branding is unavailable" }),
    ).toContainText("Branding is unavailable");
  }
  async expectValues(name: string, greeting: string) {
    await expect(
      this.page.getByRole("textbox", { name: "Application name", exact: true }),
    ).toHaveValue(name);
    await expect(
      this.page.getByRole("textbox", { name: "Greeting", exact: true }),
    ).toHaveValue(greeting);
  }
  async cancel() {
    await this.page
      .getByRole("button", { name: "Cancel", exact: true })
      .click();
  }
  async reload() {
    await this.page
      .getByRole("button", { name: "Reload", exact: true })
      .click();
  }
  async refresh() {
    await this.page.reload();
  }
  async returnFromAudit() {
    await this.page.goBack();
  }
  async expectReviewedLogo() {
    await expect(
      this.page.getByRole("img", { name: "OrgMesh default", exact: true }),
    ).toHaveAttribute("src", "/orgmesh.svg");
  }

  async interruptSession() {
    await this.page.context().clearCookies();
    await this.page.reload();
    await expect(this.page).toHaveURL(/\/auth\//);
    await expect(
      this.page.getByRole("textbox", { name: "Application name", exact: true }),
    ).toHaveCount(0);
  }

  async makeSavesUnavailable() {
    const attempts: { key: string | undefined; body: string | null }[] = [];
    await this.page.route(`**${API}/branding`, async (route) => {
      if (route.request().method() !== "PATCH") return route.continue();
      attempts.push({
        key: route.request().headers()["idempotency-key"],
        body: route.request().postData(),
      });
      await route.fulfill({
        status: 503,
        contentType: "application/json",
        body: "{}",
      });
    });
    return attempts;
  }
}
