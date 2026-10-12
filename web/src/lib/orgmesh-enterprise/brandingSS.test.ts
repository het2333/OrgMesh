import { fetchAppName, generateFaviconMetadata } from "@/lib/app/svcSS";
import { fetchSettingsSS } from "@/lib/settings/svcSS";
import { fetchSS } from "@/lib/utilsSS";

jest.mock("@/lib/utilsSS", () => ({ fetchSS: jest.fn() }));
jest.mock("@/lib/constants", () => ({
  HOST_URL: "http://localhost:3000",
  SERVER_SIDE_ONLY__PAID_ENTERPRISE_FEATURES_ENABLED: true,
  CUSTOM_ANALYTICS_ENABLED: true,
}));

const serverFetch = jest.mocked(fetchSS);
beforeEach(() => {
  // Replace only the server HTTP boundary; keep all settings derivation real.
  serverFetch.mockImplementation(
    async (path) =>
      new Response(
        JSON.stringify(
          path === "/orgmesh-enterprise/v1/branding"
            ? {
                name: "Northstar",
                greeting: "Welcome",
                logo_asset_id: "orgmesh-default",
                source: "static",
                version: 0,
              }
            : path === "/settings"
              ? {}
              : {}
        ),
        { status: path.includes("enterprise-settings") ? 503 : 200 }
      )
  );
});

test("SSR name and favicon use the independent approved static branding", async () => {
  expect(await fetchAppName()).toBe("Northstar");
  expect(await generateFaviconMetadata()).toEqual({ icon: "/orgmesh.svg" });
  expect(
    serverFetch.mock.calls.some(([path]) =>
      path.includes("enterprise-settings")
    )
  ).toBe(false);
});

test("legacy settings and analytics outages cannot fail the new SSR brand path", async () => {
  const settings = await fetchSettingsSS();
  expect(settings?.appName).toBe("Northstar");
  expect(settings?.greeting).toBe("Welcome");
  expect(
    serverFetch.mock.calls.some(([path]) =>
      path.includes("enterprise-settings")
    )
  ).toBe(false);
});

// Returning the decode promise without awaiting it would skip the fallback catch.
test("SSR malformed branding keeps the approved default instead of rejecting", async () => {
  serverFetch.mockResolvedValue(
    new Response(
      JSON.stringify({
        name: "Unreviewed",
        greeting: "",
        logo_asset_id: "https://evil.example/logo",
        source: "dynamic",
        version: 1,
      })
    )
  );
  expect(await fetchAppName()).toBe("OrgMesh");
});
