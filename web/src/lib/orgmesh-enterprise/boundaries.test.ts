import {
  fetchEnterpriseAudit,
  fetchEnterpriseCapabilities,
  fetchEnterpriseContext,
  fetchEnterpriseUsage,
  fetchOrgMeshBranding,
  patchOrgMeshBranding,
} from "@/lib/orgmesh-enterprise/svc";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const summaryFixture = JSON.parse(
  readFileSync(
    resolve(
      process.cwd(),
      "../contracts/orgmesh-enterprise/fixtures/usage-summary.json"
    ),
    "utf8"
  )
);

// A legacy or external destination added to any new browser API method fails this test.
test("new browser paths use only the same-origin BFF and no browser identity fields", async () => {
  const calls: { url: string; init: RequestInit | undefined }[] = [];
  const brand = {
    name: "OrgMesh",
    greeting: "",
    logo_asset_id: "orgmesh-default",
    version: 0,
    source: "static",
  };
  const fetchSpy = jest
    .spyOn(global, "fetch")
    .mockImplementation(async (input, init) => {
      const url = String(input);
      calls.push({ url, init });
      let data: unknown = brand;
      if (url.includes("/capabilities"))
        data = {
          branding_enabled: true,
          audit_enabled: true,
          usage_enabled: true,
          static_branding_version: 1,
        };
      if (url.includes("/context"))
        data = { user_id: "admin", tenant_id: "public" };
      if (url.includes("/audit/events"))
        data = { events: [], next_cursor: null };
      if (url.includes("/usage/summary")) data = summaryFixture.summary;
      return new Response(JSON.stringify(data), { status: 200 });
    });
  try {
    expect(await fetchOrgMeshBranding()).toEqual(brand);
    expect(
      await patchOrgMeshBranding(
        {
          expected_version: 0,
          name: "OrgMesh",
          greeting: "",
          logo_asset_id: "orgmesh-default",
        },
        "22222222-2222-4222-8222-222222222222"
      )
    ).toEqual(brand);
    expect((await fetchEnterpriseCapabilities()).usage_enabled).toBe(true);
    expect(await fetchEnterpriseContext()).toEqual({
      user_id: "admin",
      tenant_id: "public",
    });
    expect(
      (
        await fetchEnterpriseAudit({
          start: "2026-10-13T00:00:00Z",
          end: "2026-10-14T00:00:00Z",
        })
      ).events
    ).toEqual([]);
    expect(
      await fetchEnterpriseUsage({
        start: "2026-10-13T00:00:00Z",
        end: "2026-10-14T00:00:00Z",
        group_by: "day",
      })
    ).toEqual(summaryFixture.summary);
    expect(calls).toHaveLength(6);
    for (const call of calls) {
      expect(call.url).toMatch(
        /^\/api\/orgmesh-enterprise\/v1\/(branding|capabilities|context|audit\/events|usage\/summary)(\?|$)/
      );
      expect(call.init?.credentials).toBe("include");
      expect(call.init?.cache).toBe("no-store");
      const headers = new Headers(call.init?.headers);
      for (const field of [
        "X-Tenant-ID",
        "X-User-ID",
        "X-Role",
        "Authorization",
      ])
        expect(headers.has(field)).toBe(false);
    }
  } finally {
    fetchSpy.mockRestore();
  }
});
