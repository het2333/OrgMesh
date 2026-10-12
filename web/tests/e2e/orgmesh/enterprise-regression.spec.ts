import { test } from "@playwright/test";
import { OrgMeshRecoveryPage } from "@tests/e2e/pages/OrgMeshRecoveryPage";

// Run each named test in its operator-prepared phase, using existing auth state.
// No global sign-up, token creation, feature-setting change, or service control occurs.
test("disabled features preserve static branding, chat and retrieval @exclusive", async ({
  page,
}) => {
  const recovery = new OrgMeshRecoveryPage(page);
  await recovery.requirePhase("disabled");
  await recovery.expectDisabled();
  await recovery.expectChatAndSearch();
});

test("Go outage preserves static branding, chat and retrieval @exclusive", async ({
  page,
}) => {
  const recovery = new OrgMeshRecoveryPage(page);
  await recovery.requirePhase("go-outage");
  await recovery.expectStaticBrand();
  await recovery.expectChatAndSearch();
});

test("enterprise database outage preserves chat and retrieval @exclusive", async ({
  page,
}) => {
  const recovery = new OrgMeshRecoveryPage(page);
  await recovery.requirePhase("db-outage");
  await recovery.expectStaticBrand();
  await recovery.expectChatAndSearch();
});
