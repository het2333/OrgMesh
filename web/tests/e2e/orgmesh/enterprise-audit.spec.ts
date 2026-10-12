import { test } from "@playwright/test";
import { OrgMeshBrandingPage } from "@tests/e2e/pages/OrgMeshBrandingPage";
import { OrgMeshAuditPage } from "@tests/e2e/pages/OrgMeshAuditPage";

test("OrgMesh audit lists a real saved change and validates its bounded filters @exclusive", async ({
  page,
}) => {
  const brand = new OrgMeshBrandingPage(page);
  await brand.requireIsolatedEnabledService();
  const original = await brand.current();
  try {
    await brand.goto();
    await brand.fill(`Audit test ${Date.now()}`, "Audit test greeting");
    await brand.save();
    await brand.expectSaved();
    const audit = new OrgMeshAuditPage(page);
    await audit.goto();
    await audit.expectChange(original.version, original.version + 1);
    await audit.selectAction(
      original.version === 0 ? "Branding created" : "Branding updated"
    );
    await audit.selectSuccess();
    await audit.apply();
    await audit.expectChange(original.version, original.version + 1);
    await audit.setRange("2026-01-01T00:00", "2026-05-01T00:00");
    await audit.apply();
    await audit.expectRangeError();
  } finally {
    await brand.restore(original);
  }
});
