import { expect, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import type {
  EnterpriseContext,
  UsageSummary,
} from "@/lib/orgmesh-enterprise/types";

const API = "/api/orgmesh-enterprise/v1";
type Scenario =
  "ready" | "waiting" | "unavailable" | "empty" | "outage" | "stale";

export class OrgMeshUsagePage {
  private scenario: Scenario = "ready";
  private enabled = true;
  private contextStatus = 200;
  private tenantId = "";
  private actorId = "";
  private revision = 7;
  private inputTokens = "10";
  private fixture: UsageSummary;
  readonly today = new Date().toISOString().slice(0, 10);

  constructor(readonly page: Page) {
    // The same wire fixture drives Go, Python, and these browser scenarios.
    this.fixture = JSON.parse(
      readFileSync(
        resolve(
          process.cwd(),
          "../contracts/orgmesh-enterprise/fixtures/usage-summary.json",
        ),
        "utf8",
      ),
    ).summary;
  }

  async useIsolatedScenarios() {
    const base = new URL(process.env.BASE_URL || "http://localhost:3000");
    expect(["localhost", "127.0.0.1", "[::1]"]).toContain(base.hostname);
    const response = await this.page.request.get(`${API}/context`);
    expect(
      response.ok(),
      "Use an existing authenticated full-admin session in the isolated app.",
    ).toBeTruthy();
    const context: EnterpriseContext = await response.json();
    this.actorId = context.user_id;
    this.tenantId = context.tenant_id;
    await this.page.route(`**${API}/capabilities`, (route) =>
      route.fulfill({
        json: {
          branding_enabled: true,
          audit_enabled: true,
          usage_enabled: this.enabled,
          static_branding_version: 1,
        },
      }),
    );
    await this.page.route(`**${API}/context`, (route) =>
      route.fulfill({
        status: this.contextStatus,
        json: {
          user_id: this.actorId,
          tenant_id: this.tenantId,
        },
      }),
    );
    await this.page.route(`**${API}/usage/summary?**`, (route) => {
      if (this.scenario === "outage")
        return route.fulfill({
          status: 503,
          json: { detail: "Service unavailable" },
        });
      const params = new URL(route.request().url()).searchParams;
      const groupBy = params.get("group_by");
      const collection = `${this.today}T00:00:00Z`;
      const yesterday = new Date(Date.parse(collection) - 86400000)
        .toISOString()
        .slice(0, 10);
      const waiting = this.scenario === "waiting";
      const available = ["ready", "stale", "empty"].includes(this.scenario);
      const end = params.get("end") ?? collection;
      return route.fulfill({
        json: {
          ...this.fixture,
          group_by: groupBy,
          status: this.scenario === "empty" ? "ready" : this.scenario,
          activated_at: `${waiting ? this.today : yesterday}T12:00:00Z`,
          collection_start: waiting
            ? new Date(Date.parse(collection) + 86400000).toISOString()
            : collection,
          coverage: available ? { from: collection, to: end } : null,
          published_at: available
            ? new Date(
                Date.now() - (this.scenario === "stale" ? 300000 : 0),
              ).toISOString()
            : null,
          revision: available ? this.revision : 0,
          groups:
            available && this.scenario !== "empty"
              ? this.fixture.groups.map((group) => ({
                  ...group,
                  value:
                    groupBy === "day"
                      ? this.today
                      : groupBy === "model"
                        ? "Example model"
                        : "Example flow",
                  totals: {
                    ...group.totals,
                    input_tokens: this.inputTokens,
                    total_tokens: (
                      BigInt(this.inputTokens) + BigInt(5)
                    ).toString(),
                  },
                }))
              : [],
        },
      });
    });
  }

  setScenario(scenario: Scenario) {
    this.scenario = scenario;
  }
  disable() {
    this.enabled = false;
  }
  interruptAuthority() {
    this.contextStatus = 403;
  }
  switchVerifiedOrganization() {
    this.tenantId = "test-tenant-b";
  }
  publishUpdatedSnapshot() {
    this.revision += 1;
    this.inputTokens = "20";
    this.scenario = "ready";
  }

  async goto() {
    await this.page.goto("/admin/orgmesh-enterprise/usage");
  }
  async visitFromBranding() {
    await this.page.goto("/admin/orgmesh-enterprise/branding");
    await this.page.goto("/admin/orgmesh-enterprise/usage");
  }
  async back() {
    await this.page.getByRole("button", { name: "Back", exact: true }).click();
    await expect(this.page).toHaveURL(/\/admin\/orgmesh-enterprise\/branding$/);
  }
  async applyDates(start: string, end: string) {
    await this.page.getByLabel("Start date (UTC)", { exact: true }).fill(start);
    await this.page
      .getByLabel("End date (UTC, inclusive)", { exact: true })
      .fill(end);
    await this.page
      .getByRole("button", { name: "Apply dates", exact: true })
      .click();
  }
  async groupBy(label: "Model" | "Flow") {
    await this.page.getByLabel("Group by", { exact: true }).click();
    await this.page.getByRole("option", { name: label, exact: true }).click();
    await this.page
      .getByRole("button", { name: "Apply dates", exact: true })
      .click();
  }
  async reload() {
    await this.page
      .getByRole("button", { name: "Reload", exact: true })
      .click();
  }
  async expectReady(total = "15") {
    const list = this.page.getByRole("list", {
      name: "Usage groups",
      exact: true,
    });
    await expect(list).toContainText(`Total tokens: ${total}`);
    await expect(list).toContainText("Incognito user");
    await expect(list).toContainText("Attributed system");
    await expect(list).toContainText("Unattributed system");
    await expect(
      this.page.getByText(/0 may mean missing pricing/),
    ).toBeVisible();
    await expect(this.page.getByText(/Published coverage/)).toBeVisible();
  }
  async expectGroup(label: "Example model" | "Example flow") {
    await expect(
      this.page.getByRole("list", { name: "Usage groups" }),
    ).toContainText(label);
  }
  async expectUnavailable() {
    await expect(
      this.page
        .getByRole("alert")
        .filter({ hasText: "No published usage snapshot" }),
    ).toContainText("No published usage snapshot");
    await expect(
      this.page.getByRole("list", { name: "Usage groups" }),
    ).toBeHidden();
  }
  async expectWaiting() {
    await expect(
      this.page.getByText(/Waiting for the first full UTC day/),
    ).toBeVisible();
    await expect(
      this.page.getByRole("list", { name: "Usage groups" }),
    ).toBeHidden();
    await expect(this.page.getByText(/Collection starts:/)).toBeVisible();
  }
  async expectEmpty() {
    await expect(
      this.page.getByText("No usage in this published range.", { exact: true }),
    ).toBeVisible();
    await expect(this.page.getByText(/Published coverage/)).toBeVisible();
  }
  async expectStale() {
    await expect(this.page.getByRole("status")).toContainText("Stale data");
    await this.expectReady();
  }
  async expectRangeError() {
    await expect(
      this.page
        .getByRole("alert")
        .filter({ hasText: "most recent 90 UTC dates" }),
    ).toContainText("most recent 90 UTC dates");
  }
  async expectDisabled() {
    await expect(
      this.page.getByText("This feature is disabled.", { exact: true }),
    ).toBeVisible();
    await expect(
      this.page.getByLabel("Start date (UTC)", { exact: true }),
    ).toBeHidden();
    await expect(
      this.page.getByRole("button", { name: "Apply dates", exact: true }),
    ).toBeHidden();
  }
}
