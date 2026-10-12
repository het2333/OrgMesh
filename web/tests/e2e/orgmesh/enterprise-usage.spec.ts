import { test } from "@playwright/test";
import { OrgMeshUsagePage } from "@tests/e2e/pages/OrgMeshUsagePage";

// These scenarios exercise the UI boundary. They do not validate publication or source reconciliation.
test("usage separates categories, validates UTC dates, groups, refreshes and returns", async ({
  page,
}) => {
  const usage = new OrgMeshUsagePage(page);
  await usage.useIsolatedScenarios();
  await usage.visitFromBranding();
  await usage.expectReady();
  await usage.applyDates("2020-01-01", usage.today);
  await usage.expectRangeError();
  await usage.applyDates(usage.today, usage.today);
  await usage.expectReady();
  await usage.groupBy("Model");
  await usage.expectGroup("Example model");
  await usage.groupBy("Flow");
  await usage.expectGroup("Example flow");
  usage.publishUpdatedSnapshot();
  await usage.reload();
  await usage.expectReady("25");
  await usage.back();
});

test("usage distinguishes first-day waiting, no snapshot and published empty data", async ({
  page,
}) => {
  const usage = new OrgMeshUsagePage(page);
  await usage.useIsolatedScenarios();
  usage.setScenario("waiting");
  await usage.goto();
  await usage.expectWaiting();
  usage.setScenario("unavailable");
  await usage.reload();
  await usage.expectUnavailable();
  usage.setScenario("empty");
  await usage.reload();
  await usage.expectEmpty();
});

test("usage outage retains only the current query and hides data after authority interruption", async ({
  page,
}) => {
  const usage = new OrgMeshUsagePage(page);
  await usage.useIsolatedScenarios();
  await usage.goto();
  await usage.expectReady();
  usage.setScenario("outage");
  await usage.reload();
  await usage.expectStale();
  await usage.groupBy("Model");
  await usage.expectUnavailable();
  usage.setScenario("ready");
  await usage.reload();
  await usage.expectReady();
  usage.interruptAuthority();
  await usage.reload();
  await usage.expectUnavailable();
});

test("verified organization change clears the previous private snapshot", async ({
  page,
}) => {
  const usage = new OrgMeshUsagePage(page);
  await usage.useIsolatedScenarios();
  await usage.goto();
  await usage.expectReady();
  usage.switchVerifiedOrganization();
  usage.setScenario("outage");
  await usage.reload();
  await usage.expectUnavailable();
});

test("disabled usage hides query controls", async ({ page }) => {
  const usage = new OrgMeshUsagePage(page);
  await usage.useIsolatedScenarios();
  usage.disable();
  await usage.goto();
  await usage.expectDisabled();
});
