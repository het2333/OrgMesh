import { Text } from "@opal/components";
import { render, screen, waitFor } from "@tests/setup/test-utils";
import { useSettings } from "@/lib/settings/hooks";

jest.mock("next/navigation", () => ({
  usePathname: jest.fn(() => "/auth/login"),
  useRouter: () => ({ push: jest.fn(), back: jest.fn(), refresh: jest.fn() }),
}));

function SettingsProbe() {
  const settings = useSettings();
  return (
    <div>
      <Text as="p">{settings.appName}</Text>
      <Text as="p">{settings.logoUrl ?? "no-logo"}</Text>
      <Text as="p">{settings.greeting ?? "no-greeting"}</Text>
      <Text as="p">{settings.error ? "fatal-settings-error" : "usable"}</Text>
    </div>
  );
}

let fetchSpy: jest.SpyInstance;
beforeEach(() => {
  require("next/navigation").usePathname.mockReturnValue("/auth/login");
  // GET independent branding: Python returns the approved static configuration during a Go outage.
  fetchSpy = jest.spyOn(global, "fetch").mockImplementation(async (url) => {
    if (String(url) === "/api/orgmesh-enterprise/v1/branding") {
      return new Response(
        JSON.stringify({
          name: "Northstar",
          greeting: "Welcome aboard",
          logo_asset_id: "orgmesh-default",
          version: 0,
          source: "static",
        }),
        { status: 200 }
      );
    }
    return new Response("{}", { status: 503 });
  });
});
afterEach(() => fetchSpy.mockRestore());

// A legacy endpoint probe from the public brand path would fail this test.
test("test_branding_never_calls_legacy_endpoint", async () => {
  render(<SettingsProbe />);
  await waitFor(() => expect(fetchSpy).toHaveBeenCalled());
  expect(
    fetchSpy.mock.calls
      .map(([url]) => String(url))
      .some((url) => url.includes("enterprise-settings"))
  ).toBe(false);
});

// Ignoring the server's static config, or promoting brand outages to fatal core errors, would fail this test.
test("test_static_custom_brand_survives_outage", async () => {
  render(<SettingsProbe />);
  expect(await screen.findByText("Northstar")).toBeInTheDocument();
  expect(screen.getByText("Welcome aboard")).toBeInTheDocument();
  expect(screen.getByText("/orgmesh.svg")).toBeInTheDocument();
  expect(screen.getByText("usable")).toBeInTheDocument();
});

import OrgMeshBrandingPage from "@/views/admin/OrgMeshBrandingPage";
import OrgMeshAuditPage from "@/views/admin/OrgMeshAuditPage";
import { setupUser, act, deferred } from "@tests/setup/test-utils";
import { Permission } from "@/lib/types";

let mockPermissions = [Permission.FULL_ADMIN_PANEL_ACCESS];
let mockActor = "11111111-1111-4111-8111-111111111111";
jest.mock("@/providers/UserProvider", () => ({
  useUser: () => ({
    user: { id: mockActor },
    userResolution: "resolved",
    permissions: mockPermissions,
  }),
}));

function adminApi(
  patch?: (init: RequestInit | undefined) => Promise<Response>
) {
  fetchSpy.mockImplementation(async (url, init) => {
    const path = String(url);
    // Public independent capabilities and branding.
    if (path.endsWith("/capabilities"))
      return new Response(
        JSON.stringify({
          branding_enabled: true,
          audit_enabled: true,
          usage_enabled: false,
          static_branding_version: 1,
        })
      );
    if (path.endsWith("/context"))
      return new Response(
        JSON.stringify({ user_id: mockActor, tenant_id: "public" })
      );
    if (path.endsWith("/branding")) {
      if (init?.method === "PATCH" && patch) return patch(init);
      return new Response(
        JSON.stringify({
          name: "Northstar",
          greeting: "Welcome aboard",
          logo_asset_id: "orgmesh-default",
          version: 1,
          source: "dynamic",
        })
      );
    }
    if (path.includes("/audit/events"))
      return new Response(JSON.stringify({ events: [], next_cursor: null }));
    return new Response("{}", { status: 503 });
  });
}

beforeEach(() => {
  mockPermissions = [Permission.FULL_ADMIN_PANEL_ACCESS];
  mockActor = "11111111-1111-4111-8111-111111111111";
});

// Showing a private audit list, or querying audit as a scoped manager, would fail this test.
test("test_audit_requires_full_admin", async () => {
  mockPermissions = [Permission.MANAGE_USER_GROUPS];
  adminApi();
  render(<OrgMeshAuditPage />);
  expect(
    await screen.findByText(/full administrator access is required/i)
  ).toBeInTheDocument();
  expect(
    fetchSpy.mock.calls.some(
      ([url]) =>
        String(url).includes("/audit/events") ||
        String(url).endsWith("/context")
    )
  ).toBe(false);
});

// Resetting form state after a 409 would fail this test.
test("test_branding_conflict_keeps_unsaved_input", async () => {
  adminApi(async () => new Response("{}", { status: 409 }));
  const user = setupUser();
  render(<OrgMeshBrandingPage />);
  const name = await screen.findByRole("textbox", {
    name: /application name/i,
  });
  await user.clear(name);
  await user.type(name, "My unsaved name");
  await user.click(screen.getByRole("button", { name: /^save$/i }));
  expect(
    await screen.findByText(/another administrator changed/i)
  ).toBeInTheDocument();
  expect(name).toHaveValue("My unsaved name");
  await user.click(screen.getByRole("button", { name: /reload/i }));
  await waitFor(() => expect(name).toHaveValue("Northstar"));
});

// Missing submit locking or rotating a retry key would fail this test.
test("prevents duplicate saves and reuses a key for an unchanged unavailable retry", async () => {
  const response = deferred<Response>();
  let attempt = 0;
  adminApi(async () =>
    ++attempt === 1 ? response.promise : new Response("{}", { status: 503 })
  );
  const user = setupUser();
  render(<OrgMeshBrandingPage />);
  const name = await screen.findByRole("textbox", {
    name: /application name/i,
  });
  await user.clear(name);
  await user.type(name, "Saved name");
  const save = screen.getByRole("button", { name: /^save$/i });
  await user.dblClick(save);
  expect(attempt).toBe(1);
  await act(async () => response.resolve(new Response("{}", { status: 503 })));
  expect(
    await screen.findByText(/unavailable.*try again/i)
  ).toBeInTheDocument();
  await user.click(save);
  const patches = fetchSpy.mock.calls.filter(
    ([, init]) => init?.method === "PATCH"
  );
  expect(patches).toHaveLength(2);
  expect(patches[0][1].headers["Idempotency-Key"]).toBe(
    patches[1][1].headers["Idempotency-Key"]
  );
  await user.type(name, " changed");
  await user.click(save);
  const changed = fetchSpy.mock.calls.filter(
    ([, init]) => init?.method === "PATCH"
  );
  expect(changed[2][1].headers["Idempotency-Key"]).not.toBe(
    changed[1][1].headers["Idempotency-Key"]
  );
});

// Persisting edited values on Cancel, or treating format version 1 as row version, would fail this test.
test("cancel discards edits and first save uses static persisted version zero", async () => {
  adminApi(
    async () =>
      new Response(
        JSON.stringify({
          name: "First brand",
          greeting: "",
          logo_asset_id: "orgmesh-default",
          version: 1,
          source: "dynamic",
        })
      )
  );
  const old = fetchSpy.getMockImplementation();
  fetchSpy.mockImplementation(async (url, init) =>
    String(url).endsWith("/branding") && init?.method !== "PATCH"
      ? new Response(
          JSON.stringify({
            name: "OrgMesh",
            greeting: "",
            logo_asset_id: "orgmesh-default",
            version: 0,
            source: "static",
          })
        )
      : old?.(url, init)
  );
  const user = setupUser();
  render(<OrgMeshBrandingPage />);
  const name = await screen.findByRole("textbox", {
    name: /application name/i,
  });
  await user.clear(name);
  await user.type(name, "Discard me");
  await user.click(screen.getByRole("button", { name: /^cancel$/i }));
  expect(name).toHaveValue("OrgMesh");
  await user.clear(name);
  await user.type(name, "First brand");
  await user.click(screen.getByRole("button", { name: /^save$/i }));
  expect(await screen.findByText(/branding saved/i)).toBeInTheDocument();
  const patch = fetchSpy.mock.calls.find(
    ([, init]) => init?.method === "PATCH"
  );
  expect(JSON.parse(patch?.[1].body)).toEqual({
    name: "First brand",
    greeting: "",
    logo_asset_id: "orgmesh-default",
    expected_version: 0,
  });
});

import { AppPopup } from "@/app/app/components/AppPopup";

// Treating explicitly enabled legacy consent-policy failures as an empty policy would fail this test.
test("enabled consent policy fails closed on an unavailable policy service", async () => {
  localStorage.clear();
  // Auth is actually EE-enabled through explicit core settings in the separate policy hook.
  jest.spyOn(require("next/navigation"), "usePathname").mockReturnValue("/app");
  fetchSpy.mockImplementation(async (url) => {
    if (String(url) === "/api/settings")
      return new Response(JSON.stringify({ ee_features_enabled: true }));
    if (String(url) === "/api/enterprise-settings")
      return new Response("{}", { status: 503 });
    return new Response(
      JSON.stringify({
        name: "Northstar",
        greeting: "",
        logo_asset_id: "orgmesh-default",
        version: 0,
        source: "static",
      })
    );
  });
  render(<AppPopup />);
  expect(await screen.findByRole("dialog")).toBeInTheDocument();
  expect(
    await screen.findByText(/service is unavailable/i)
  ).toBeInTheDocument();
});

// Dropping the original consent fields when splitting branding would fail this test.
test("explicitly enabled consent notice keeps its checkbox and blocks continuation", async () => {
  localStorage.clear();
  jest.spyOn(require("next/navigation"), "usePathname").mockReturnValue("/app");
  fetchSpy.mockImplementation(async (url) => {
    if (String(url) === "/api/settings")
      return new Response(JSON.stringify({ ee_features_enabled: true }));
    if (String(url) === "/api/enterprise-settings")
      return new Response(
        JSON.stringify({
          application_name: "Ignored old brand",
          use_custom_logo: true,
          use_custom_logotype: false,
          logo_display_style: "logo_only",
          custom_nav_items: [],
          custom_lower_disclaimer_content: null,
          custom_header_content: null,
          two_lines_for_chat_header: null,
          custom_popup_header: "Policy notice",
          custom_popup_content: "Review the workspace rules.",
          enable_consent_screen: true,
          consent_screen_prompt: "I accept the workspace rules",
          show_first_visit_notice: true,
          custom_greeting_message: null,
          custom_login_subtitle: null,
          custom_help_link_url: null,
          custom_help_link_label: null,
          hide_onyx_branding: false,
        })
      );
    return new Response(
      JSON.stringify({
        name: "Northstar",
        greeting: "",
        logo_asset_id: "orgmesh-default",
        version: 0,
        source: "static",
      })
    );
  });
  const user = setupUser();
  render(<AppPopup />);
  expect(await screen.findByText("Policy notice")).toBeInTheDocument();
  expect(screen.getByRole("checkbox")).not.toBeChecked();
  await user.click(screen.getByRole("button", { name: /^start$/i }));
  expect(screen.getByRole("dialog")).toBeInTheDocument();
  await user.click(screen.getByRole("checkbox"));
  await user.click(screen.getByRole("button", { name: /^start$/i }));
  await waitFor(() =>
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
  );
});

import { useEnterpriseCacheLifecycle } from "@/lib/orgmesh-enterprise/hooks";

const firstEvent = {
  event_id: "33333333-3333-4333-8333-333333333333",
  created_at: "2026-10-12T10:00:00Z",
  user_id: "11111111-1111-4111-8111-111111111111",
  actor_kind: "user",
  resource_id: "branding-config",
  action: "branding.created",
  result: "success",
  before_version: 0,
  after_version: 1,
  changed_fields: ["name", "greeting", "logo_asset_id"],
  request_id: "44444444-4444-4444-8444-444444444444",
};

// A mismatched /me actor must never make a stale private context usable.
test("audit rejects a context for another authenticated actor", async () => {
  adminApi();
  const upstream = fetchSpy.getMockImplementation();
  fetchSpy.mockImplementation(async (url, init) =>
    String(url).endsWith("/context")
      ? new Response(
          JSON.stringify({ user_id: "another-user", tenant_id: "public" })
        )
      : upstream?.(url, init)
  );
  render(<OrgMeshAuditPage />);
  expect(
    await screen.findByText(/service is unavailable/i)
  ).toBeInTheDocument();
  expect(
    fetchSpy.mock.calls.some(([url]) => String(url).includes("/audit/events"))
  ).toBe(false);
});

// Revalidating only the uninitialized audit key would leave a failed context unrecoverable.
test("audit reload recovers a failed verified organization context", async () => {
  adminApi();
  const upstream = fetchSpy.getMockImplementation();
  let contextAttempts = 0;
  fetchSpy.mockImplementation(async (url, init) => {
    if (String(url).endsWith("/context") && ++contextAttempts === 1)
      return new Response("{}", { status: 503 });
    if (String(url).includes("/audit/events"))
      return new Response(
        JSON.stringify({ events: [firstEvent], next_cursor: null })
      );
    return upstream?.(url, init);
  });
  const user = setupUser();
  render(<OrgMeshAuditPage />);
  expect(
    await screen.findByText(/service is unavailable/i)
  ).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: /reload/i }));
  expect(await screen.findByText("Versions 0 → 1")).toBeInTheDocument();
  expect(screen.getByText("Versions 0 → 1")).toBeInTheDocument();
  expect(
    screen.getByText(/Changed fields: Name, Greeting/)
  ).toBeInTheDocument();
});

function AuditSession() {
  useEnterpriseCacheLifecycle(mockActor);
  return <OrgMeshAuditPage />;
}

// Keeping old private SWR entries or showing their data on an account change would fail this test.
test("account change clears private audit cache before showing the next organization's list", async () => {
  const cache = new Map();
  adminApi();
  const upstream = fetchSpy.getMockImplementation();
  fetchSpy.mockImplementation(async (url, init) =>
    String(url).includes("/audit/events")
      ? new Response(
          JSON.stringify({
            events: mockActor.startsWith("1111") ? [firstEvent] : [],
            next_cursor: null,
          })
        )
      : upstream?.(url, init)
  );
  const view = render(<AuditSession />, {
    swrConfig: { provider: () => cache },
  });
  expect(await screen.findByText("Versions 0 → 1")).toBeInTheDocument();
  mockActor = "22222222-2222-4222-8222-222222222222";
  view.rerender(<AuditSession />);
  expect(screen.queryByText("Versions 0 → 1")).not.toBeInTheDocument();
  expect(await screen.findByText(/no branding changes/i)).toBeInTheDocument();
  expect(
    [...cache.values()].some(
      (state) => state.data?.events?.[0]?.user_id === firstEvent.user_id
    )
  ).toBe(false);
});

// A disabled feature must not issue private audit reads or make public branding unusable.
test("disabled audit shows a useful state without querying events", async () => {
  adminApi();
  const upstream = fetchSpy.getMockImplementation();
  fetchSpy.mockImplementation(async (url, init) =>
    String(url).endsWith("/capabilities")
      ? new Response(
          JSON.stringify({
            branding_enabled: false,
            audit_enabled: false,
            usage_enabled: false,
            static_branding_version: 1,
          })
        )
      : upstream?.(url, init)
  );
  render(<OrgMeshAuditPage />);
  expect(await screen.findByText(/feature is disabled/i)).toBeInTheDocument();
  expect(
    fetchSpy.mock.calls.some(([url]) => String(url).includes("/audit/events"))
  ).toBe(false);
});

// A unsafe remote asset response cannot make the browser request that asset.
test("malformed or remote logo branding keeps the reviewed safe public default", async () => {
  fetchSpy.mockResolvedValue(
    new Response(
      JSON.stringify({
        name: "Untrusted",
        greeting: "<script>alert(1)</script>",
        logo_asset_id: "https://evil.example/logo.svg",
        version: 1,
        source: "dynamic",
      })
    )
  );
  render(<SettingsProbe />);
  await waitFor(() => expect(fetchSpy).toHaveBeenCalled());
  expect(screen.getByText("OrgMesh")).toBeInTheDocument();
  expect(screen.getByText("/orgmesh.svg")).toBeInTheDocument();
  expect(screen.getByText("usable")).toBeInTheDocument();
});

// Sending raw executable fields to PATCH instead of validating them would fail this test.
test("plain-text limits prevent an unsafe save without losing input", async () => {
  adminApi();
  const user = setupUser();
  render(<OrgMeshBrandingPage />);
  const name = await screen.findByRole("textbox", {
    name: /application name/i,
  });
  await user.clear(name);
  await user.type(name, "<img src=x onerror=alert(1)>");
  await user.click(screen.getByRole("button", { name: /^save$/i }));
  expect(
    await screen.findByText(/Use plain text without HTML/i)
  ).toBeInTheDocument();
  expect(name).toHaveValue("<img src=x onerror=alert(1)>");
  expect(fetchSpy.mock.calls.some(([, init]) => init?.method === "PATCH")).toBe(
    false
  );
});

// A malformed private response must show an unavailable state, not crash the page.
test("malformed audit pages remain unavailable and never display unverified events", async () => {
  adminApi();
  const upstream = fetchSpy.getMockImplementation();
  fetchSpy.mockImplementation(async (url, init) =>
    String(url).includes("/audit/events")
      ? new Response(JSON.stringify({ events: null, next_cursor: null }))
      : upstream?.(url, init)
  );
  render(<OrgMeshAuditPage />);
  expect(
    await screen.findByText(/service is unavailable/i)
  ).toBeInTheDocument();
});

import { Button } from "@opal/components";
import { useEnterpriseContext } from "@/lib/orgmesh-enterprise/hooks";
import { useCustomFooterContent } from "@/lib/app/hooks";
import { RootLayout } from "@opal/layouts";
import { markdown } from "@opal/utils";

function ContextRefreshControl() {
  const context = useEnterpriseContext();
  return <Button onClick={() => void context.mutate()}>Refresh context</Button>;
}

// A failed context refresh must revoke usable frontend authority without discarding the draft.
test.each([401, 403, 503])(
  "context refresh failure %s makes the draft read-only until verified recovery",
  async (status) => {
    adminApi();
    const upstream = fetchSpy.getMockImplementation();
    let unavailable = false;
    fetchSpy.mockImplementation(async (url, init) =>
      String(url).endsWith("/context") && unavailable
        ? new Response("{}", { status })
        : upstream?.(url, init)
    );
    const user = setupUser();
    render(
      <>
        <OrgMeshBrandingPage />
        <ContextRefreshControl />
      </>
    );
    const name = await screen.findByRole("textbox", {
      name: /application name/i,
    });
    await user.clear(name);
    await user.type(name, "Keep my draft");
    const save = screen.getByRole("button", { name: /^save$/i });
    expect(save).toBeEnabled();
    unavailable = true;
    await user.click(screen.getByRole("button", { name: "Refresh context" }));
    await waitFor(() => expect(save).toBeDisabled());
    expect(name).toHaveValue("Keep my draft");
    expect(name).toBeDisabled();
    await user.click(save);
    expect(
      fetchSpy.mock.calls.some(([, init]) => init?.method === "PATCH")
    ).toBe(false);
    unavailable = false;
    await user.click(screen.getByRole("button", { name: "Refresh context" }));
    await waitFor(() => expect(save).toBeEnabled());
    expect(name).toHaveValue("Keep my draft");
    expect(name).toBeEnabled();
  }
);

// Minute truncation would exclude a change saved immediately before opening audit.
test("opening audit immediately after a save includes nonzero seconds in its default end", async () => {
  jest.useFakeTimers({
    doNotFake: [
      "setTimeout",
      "clearTimeout",
      "setInterval",
      "clearInterval",
      "performance",
      "queueMicrotask",
      "requestAnimationFrame",
      "cancelAnimationFrame",
      "setImmediate",
      "clearImmediate",
      "nextTick",
    ],
  });
  jest.setSystemTime(new Date("2026-10-12T12:01:45.000Z"));
  try {
    let savedEvent: typeof firstEvent | undefined;
    adminApi(async () => {
      savedEvent = {
        ...firstEvent,
        created_at: "2026-10-12T12:01:45.000Z",
        action: "branding.updated",
        before_version: 1,
        after_version: 2,
      };
      return new Response(
        JSON.stringify({
          name: "Brand just saved",
          greeting: "",
          logo_asset_id: "orgmesh-default",
          version: 2,
          source: "dynamic",
        })
      );
    });
    const upstream = fetchSpy.getMockImplementation();
    fetchSpy.mockImplementation(async (url, init) => {
      if (String(url).includes("/audit/events")) {
        const query = new URL(String(url), "http://localhost").searchParams;
        const included =
          savedEvent &&
          Date.parse(savedEvent.created_at) <
            Date.parse(query.get("end") ?? "");
        return new Response(
          JSON.stringify({
            events: included ? [savedEvent] : [],
            next_cursor: null,
          })
        );
      }
      return upstream?.(url, init);
    });
    const user = setupUser();
    const view = render(<OrgMeshBrandingPage />);
    const name = await screen.findByRole("textbox", {
      name: /application name/i,
    });
    await user.clear(name);
    await user.type(name, "Brand just saved");
    await user.click(screen.getByRole("button", { name: /^save$/i }));
    expect(await screen.findByText("Branding saved.")).toBeInTheDocument();
    jest.setSystemTime(new Date("2026-10-12T12:01:45.500Z"));
    view.rerender(<OrgMeshAuditPage />);
    expect(await screen.findByText("Versions 1 → 2")).toBeInTheDocument();
    const call = fetchSpy.mock.calls.find(([url]) =>
      String(url).includes("/audit/events")
    );
    expect(
      new URL(String(call?.[0]), "http://localhost").searchParams.get("end")
    ).toBe("2026-10-12T12:01:45.500Z");
  } finally {
    jest.useRealTimers();
  }
});

function PolicyFooter() {
  const content = useCustomFooterContent();
  return (
    <RootLayout.Footer>
      <Text as="p">{markdown(content)}</Text>
    </RootLayout.Footer>
  );
}

// The independent brand failure cannot remove an explicitly enabled disclaimer policy.
test("enabled lower disclaimer remains in the footer during an independent-brand outage", async () => {
  require("next/navigation").usePathname.mockReturnValue("/app");
  fetchSpy.mockImplementation(async (url) => {
    if (String(url) === "/api/settings")
      return new Response(
        JSON.stringify({ ee_features_enabled: true, version: "test" })
      );
    if (String(url) === "/api/enterprise-settings")
      return new Response(
        JSON.stringify({
          custom_lower_disclaimer_content: "Configured workspace disclaimer",
        })
      );
    if (String(url).endsWith("/branding"))
      return new Response("{}", { status: 503 });
    return new Response("{}", { status: 503 });
  });
  render(<PolicyFooter />);
  expect(
    await screen.findByText("Configured workspace disclaimer")
  ).toBeInTheDocument();
});
