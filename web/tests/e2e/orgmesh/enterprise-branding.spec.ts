import { test, expect } from "@playwright/test";
import { OrgMeshBrandingPage } from "@tests/e2e/pages/OrgMeshBrandingPage";
import { OrgMeshAuditPage } from "@tests/e2e/pages/OrgMeshAuditPage";
import type { BrandingView } from "@/lib/orgmesh-enterprise/types";

// Run only on the isolated, single-organization stack. The suite writes test branding and restores its fields.
test.describe("OrgMesh branding @exclusive", () => {
  let original: BrandingView | undefined;
  test.beforeEach(async ({ page }) => {
    original = undefined;
    const brand = new OrgMeshBrandingPage(page);
    await brand.requireIsolatedEnabledService();
    original = await brand.current();
    await brand.goto();
  });
  test.afterEach(async ({ page }) => {
    if (original) await new OrgMeshBrandingPage(page).restore(original);
  });

  test("save, duplicate click, refresh and return keep one persisted version", async ({
    page,
  }) => {
    if (!original) throw new Error("Missing isolated branding fixture");
    const brand = new OrgMeshBrandingPage(page);
    const name = `Brand test ${Date.now()}`;
    await brand.fill(name, "Welcome to this workspace");
    await brand.save(true);
    await brand.expectSaved();
    const saved = await brand.current();
    expect(saved.version).toBe(original.version + 1);
    await brand.refresh();
    await brand.expectValues(name, "Welcome to this workspace");
    await brand.expectReviewedLogo();
    await new OrgMeshAuditPage(page).goto();
    await brand.returnFromAudit();
    await brand.expectValues(name, "Welcome to this workspace");
  });

  test("a conflict preserves edits until cancel or reload", async ({
    page,
  }) => {
    if (!original) throw new Error("Missing isolated branding fixture");
    const brand = new OrgMeshBrandingPage(page);
    await brand.fill("My unsaved change", "Keep this draft");
    await brand.externalSave({
      name: "Concurrent change",
      greeting: original.greeting,
      logo_asset_id: original.logo_asset_id,
      expected_version: original.version,
    });
    await brand.save();
    await brand.expectConflict();
    await brand.expectValues("My unsaved change", "Keep this draft");
    await brand.cancel();
    await brand.expectValues(original.name, original.greeting);
    await brand.reload();
    await brand.expectValues("Concurrent change", original.greeting);
  });

  test("unavailable retries retain edits and idempotency identity on a small screen", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    const brand = new OrgMeshBrandingPage(page);
    const attempts = await brand.makeSavesUnavailable();
    const longName = "界".repeat(50);
    await brand.fill(longName, "Draft greeting");
    await brand.save();
    await brand.expectUnavailable();
    await brand.save();
    await brand.expectUnavailable();
    await brand.expectValues(longName, "Draft greeting");
    expect(attempts).toHaveLength(2);
    expect(attempts[0]?.key).toBe(attempts[1]?.key);
    expect(attempts[0]?.body).toBe(attempts[1]?.body);
  });
});

// This test changes only the browser session, not the test account.
test("OrgMesh private brand form disappears when login is interrupted @exclusive", async ({
  page,
}) => {
  const brand = new OrgMeshBrandingPage(page);
  await brand.requireIsolatedEnabledService();
  await brand.goto();
  await brand.fill("Unsaved session draft", "");
  await brand.interruptSession();
});
