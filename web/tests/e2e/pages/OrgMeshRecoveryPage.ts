import { expect, type Page } from "@playwright/test";
import { sendMessageAndCaptureStreamPackets } from "@tests/e2e/utils/chatStream";

export class OrgMeshRecoveryPage {
  constructor(readonly page: Page) {}

  async requirePhase(phase: string) {
    expect(
      process.env.ORGMESH_RECOVERY_PHASE,
      "Prepare the named isolated recovery phase first"
    ).toBe(phase);
    const base = new URL(process.env.BASE_URL || "http://localhost:3000");
    expect(["localhost", "127.0.0.1", "[::1]"]).toContain(base.hostname);
    const context = await this.page.request.get(
      "/api/orgmesh-enterprise/v1/context"
    );
    expect(
      context.status(),
      "Supply an existing authorized admin storage state"
    ).toBe(200);
  }

  async expectStaticBrand() {
    const response = await this.page.request.get(
      "/api/orgmesh-enterprise/v1/branding"
    );
    expect(response.status()).toBe(200);
    expect(await response.json()).toMatchObject({
      source: "static",
      version: 0,
      logo_asset_id: "orgmesh-default",
    });
  }

  async expectDisabled() {
    const response = await this.page.request.get(
      "/api/orgmesh-enterprise/v1/capabilities"
    );
    expect(await response.json()).toMatchObject({
      branding_enabled: false,
      audit_enabled: false,
      usage_enabled: false,
    });
    for (const path of ["audit/events", "usage/summary"]) {
      expect(
        (
          await this.page.request.get(`/api/orgmesh-enterprise/v1/${path}`)
        ).status()
      ).toBe(503);
    }
    await this.expectStaticBrand();
  }

  async expectChatAndSearch() {
    expect(process.env.ORGMESH_RECOVERY_MOCK_LLM_APPROVED).toBe("true");
    await this.page.goto("/app?compose=1");
    await sendMessageAndCaptureStreamPackets(this.page, "Recovery smoke test", {
      mockLlmResponse: "OrgMesh recovery mock answer",
    });
    await expect(this.page.getByTestId("onyx-ai-message").last()).toContainText(
      "OrgMesh recovery mock answer"
    );
    const documentId = process.env.ORGMESH_RECOVERY_SEARCH_DOCUMENT_ID;
    expect(
      documentId,
      "Prepare the existing indexed search fixture"
    ).toBeTruthy();
    const response = await this.page.request.post("/api/admin/search", {
      data: { query: "orgmesh recovery fixture", filters: {} },
    });
    expect(response.status()).toBe(200);
    const result = await response.json();
    expect(
      result.documents.some(
        (document: { document_id: string }) =>
          document.document_id === documentId
      )
    ).toBe(true);
  }
}
