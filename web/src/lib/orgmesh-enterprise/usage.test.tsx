import { Button, Text } from "@opal/components";
import {
  act,
  deferred,
  fireEvent,
  render,
  screen,
  setupUser,
  waitFor,
} from "@tests/setup/test-utils";
import { Permission } from "@/lib/types";
import {
  useEnterpriseCacheLifecycle,
  useEnterpriseCapabilities,
  useEnterpriseContext,
  useEnterpriseUsage,
} from "@/lib/orgmesh-enterprise/hooks";

jest.mock("next/navigation", () => ({
  useRouter: () => ({ push: jest.fn(), back: jest.fn(), refresh: jest.fn() }),
}));
let mockActor: string | undefined = "actor-a";
let mockTenant = "tenant-a";
let mockAdmin = true;
jest.mock("@/providers/UserProvider", () => ({
  useUser: () => ({
    user: mockActor ? { id: mockActor } : null,
    userResolution: "resolved",
    permissions: mockAdmin ? [Permission.FULL_ADMIN_PANEL_ACCESS] : [],
  }),
}));
const query = {
  start: "2026-10-12T00:00:00Z",
  end: "2026-10-14T00:00:00Z",
  group_by: "day" as const,
};
const totals = {
  input_tokens: "9007199254740993",
  output_tokens: "5",
  total_tokens: "9007199254740998",
  cache_read_tokens: "4",
  cache_creation_tokens: "2",
  cost_cents: "999999999999.123456",
};
const summary = {
  group_by: "day",
  status: "ready",
  activated_at: "2026-10-12T12:00:00Z",
  collection_start: "2026-10-13T00:00:00Z",
  coverage: { from: "2026-10-13T00:00:00Z", to: "2026-10-14T00:00:00Z" },
  published_at: "2026-10-13T12:00:00Z",
  revision: 7,
  groups: [
    { value: "2026-10-13", category: "USER", incognito: false, totals },
    { value: "2026-10-13", category: "USER", incognito: true, totals },
    {
      value: "2026-10-13",
      category: "SYSTEM_ATTRIBUTED",
      incognito: false,
      totals,
    },
    {
      value: "2026-10-13",
      category: "SYSTEM_UNATTRIBUTED",
      incognito: false,
      totals,
    },
  ],
  cost_basis: "source_estimate_usd_cents",
  cost_notice:
    "Source-estimated USD cents; 0 may mean missing pricing. Not settled charges.",
};
beforeAll(() => {
  // Radix uses browser pointer and scrolling APIs that jsdom does not implement.
  Element.prototype.scrollIntoView = jest.fn();
  Element.prototype.hasPointerCapture = jest.fn(() => false);
  Element.prototype.setPointerCapture = jest.fn();
  Element.prototype.releasePointerCapture = jest.fn();
});
let fetchSpy: jest.SpyInstance;
let usageStatus = 200;
let contextStatus = 200;
let usageEnabled = true;
let result: typeof summary = summary;
beforeEach(() => {
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
  jest.setSystemTime(new Date("2026-10-13T12:00:00Z"));
  mockActor = "actor-a";
  mockTenant = "tenant-a";
  mockAdmin = true;
  usageStatus = 200;
  contextStatus = 200;
  usageEnabled = true;
  result = summary;
  fetchSpy = jest.spyOn(global, "fetch").mockImplementation(async (url) => {
    const path = String(url);
    if (path.endsWith("/capabilities"))
      return new Response(
        JSON.stringify({
          branding_enabled: true,
          audit_enabled: true,
          usage_enabled: usageEnabled,
          static_branding_version: 1,
        })
      );
    if (path.endsWith("/context"))
      return new Response(
        JSON.stringify({
          user_id: mockActor,
          tenant_id: mockTenant,
        }),
        { status: contextStatus }
      );
    if (path.includes("/usage/summary"))
      return new Response(JSON.stringify(result), { status: usageStatus });
    return new Response("{}", { status: 503 });
  });
});
afterEach(() => {
  fetchSpy.mockRestore();
  jest.useRealTimers();
});

function ContextRefresh() {
  const context = useEnterpriseContext();
  const capabilities = useEnterpriseCapabilities();
  return (
    <>
      <Button onClick={() => void context.mutate()}>Verify context</Button>
      <Button onClick={() => void capabilities.mutate()}>
        Verify capabilities
      </Button>
    </>
  );
}
function UsageProbe({ selection = query }: { selection?: typeof query }) {
  useEnterpriseCacheLifecycle(mockActor);
  const state = useEnterpriseUsage(selection);
  return (
    <>
      <Text as="p">{state.unavailable ? "Unavailable" : "Available"}</Text>
      <Text as="p">{state.stale ? "Stale" : "Current"}</Text>
      <Text as="p">{JSON.stringify(state.data ?? null)}</Text>
      <Text as="p">{state.activationBoundary ?? "No boundary"}</Text>
      <Button onClick={() => void state.reload()}>Refresh usage</Button>
      <ContextRefresh />
    </>
  );
}

// A retained old-actor cache entry or keepPreviousData would expose the old snapshot.
test("test_account_switch_clears_usage", async () => {
  const cache = new Map();
  const view = render(<UsageProbe />, { swrConfig: { provider: () => cache } });
  expect(await screen.findByText(/9007199254740993/)).toBeInTheDocument();
  mockActor = "actor-b";
  mockTenant = "tenant-b";
  usageStatus = 503;
  view.rerender(<UsageProbe />);
  expect(screen.queryByText(/9007199254740993/)).not.toBeInTheDocument();
  expect(await screen.findByText("Unavailable")).toBeInTheDocument();
  expect([...cache.values()].some((entry) => entry.data?.groups?.length)).toBe(
    false
  );
});

// Returning fabricated empty totals would misrepresent an absent publication as zero usage.
test("test_no_snapshot_is_not_zero", async () => {
  result = {
    ...summary,
    status: "unavailable",
    coverage: null,
    published_at: null,
    revision: 0,
    groups: [],
  } as unknown as typeof summary;
  render(<UsageProbe />);
  expect(await screen.findByText("Unavailable")).toBeInTheDocument();
  expect(screen.queryByText(/total_tokens/)).not.toBeInTheDocument();
});

// Combining categories, or turning incognito users into system usage, would fail this contract.
test("test_user_system_separated", async () => {
  render(<UsageProbe />);
  const groups = await screen.findByText(/SYSTEM_UNATTRIBUTED/);
  expect(groups).toHaveTextContent('"category":"USER","incognito":true');
  expect(groups).toHaveTextContent('"category":"SYSTEM_ATTRIBUTED"');
  expect(groups).toHaveTextContent('"total_tokens":"9007199254740998"');
});

// Using the requested start as published coverage would include the activation day's partial data.
test("test_pre_activation_day_excluded", async () => {
  render(<UsageProbe />);
  expect(await screen.findByText("2026-10-13T00:00:00Z")).toBeInTheDocument();
  expect(
    await screen.findByText(/"from":"2026-10-13T00:00:00Z"/)
  ).toBeInTheDocument();
});

// Losing the source pricing notice would let a zero estimate imply a settled or free charge.
test("test_unknown_pricing_label", async () => {
  render(<UsageProbe />);
  expect(
    await screen.findByText(/0 may mean missing pricing/)
  ).toBeInTheDocument();
});

// A service outage may retain only the existing verified query, never another date range.
test("same-scope outage is stale but a different query has no fallback", async () => {
  const user = setupUser();
  const view = render(<UsageProbe />);
  expect(await screen.findByText(/9007199254740993/)).toBeInTheDocument();
  usageStatus = 503;
  await user.click(screen.getByRole("button", { name: "Refresh usage" }));
  expect(await screen.findByText("Stale")).toBeInTheDocument();
  expect(screen.getByText(/9007199254740993/)).toBeInTheDocument();
  view.rerender(
    <UsageProbe selection={{ ...query, start: "2026-10-13T00:00:00Z" }} />
  );
  expect(screen.queryByText(/9007199254740993/)).not.toBeInTheDocument();
  expect(await screen.findByText("Unavailable")).toBeInTheDocument();
});

// Revoked authority must hide even already published results.
test.each([401, 403, 503])(
  "failed authority context %s hides cached usage",
  async (status) => {
    const user = setupUser();
    render(<UsageProbe />);
    expect(await screen.findByText(/9007199254740993/)).toBeInTheDocument();
    contextStatus = status;
    await user.click(screen.getByRole("button", { name: "Verify context" }));
    expect(await screen.findByText("Unavailable")).toBeInTheDocument();
    expect(screen.queryByText(/9007199254740993/)).not.toBeInTheDocument();
  }
);

test.each([401, 403])(
  "summary authority failure %s cannot retain stale results",
  async (status) => {
    const user = setupUser();
    render(<UsageProbe />);
    expect(await screen.findByText(/9007199254740993/)).toBeInTheDocument();
    usageStatus = status;
    await user.click(screen.getByRole("button", { name: "Refresh usage" }));
    expect(await screen.findByText("Unavailable")).toBeInTheDocument();
    expect(screen.queryByText(/9007199254740993/)).not.toBeInTheDocument();
  }
);

// The current actor can switch organizations after the server verifies a new tenant.
test("verified tenant switch clears usage for the same actor", async () => {
  const cache = new Map();
  const user = setupUser();
  render(<UsageProbe />, { swrConfig: { provider: () => cache } });
  expect(await screen.findByText(/9007199254740993/)).toBeInTheDocument();
  mockTenant = "tenant-b";
  usageStatus = 503;
  await user.click(screen.getByRole("button", { name: "Verify context" }));
  expect(await screen.findByText("Unavailable")).toBeInTheDocument();
  expect(screen.queryByText(/9007199254740993/)).not.toBeInTheDocument();
  expect([...cache.values()].some((entry) => entry.data?.groups?.length)).toBe(
    false
  );
});

test("logout hides and clears usage even when the page stays mounted", async () => {
  const cache = new Map();
  const view = render(<UsageProbe />, { swrConfig: { provider: () => cache } });
  expect(await screen.findByText(/9007199254740993/)).toBeInTheDocument();
  mockActor = undefined;
  view.rerender(<UsageProbe />);
  expect(screen.queryByText(/9007199254740993/)).not.toBeInTheDocument();
  await waitFor(() =>
    expect(
      [...cache.values()].some((entry) => entry.data?.groups?.length)
    ).toBe(false)
  );
});

test("disabled capability and non-admin authority never query usage", async () => {
  usageEnabled = false;
  render(<UsageProbe />);
  await waitFor(() => expect(fetchSpy).toHaveBeenCalled());
  expect(
    fetchSpy.mock.calls.some(([url]) => String(url).includes("/usage/summary"))
  ).toBe(false);
});

test("late response from a previous actor cannot refill private cache", async () => {
  const pending = deferred<Response>();
  const upstream = fetchSpy.getMockImplementation();
  fetchSpy.mockImplementation(async (url, init) =>
    String(url).includes("/usage/summary")
      ? pending.promise
      : upstream?.(url, init)
  );
  const cache = new Map();
  const view = render(<UsageProbe />, { swrConfig: { provider: () => cache } });
  await waitFor(() =>
    expect(
      fetchSpy.mock.calls.some(([url]) =>
        String(url).includes("/usage/summary")
      )
    ).toBe(true)
  );
  mockActor = undefined;
  view.rerender(<UsageProbe />);
  await act(async () => pending.resolve(new Response(JSON.stringify(summary))));
  expect(screen.queryByText(/9007199254740993/)).not.toBeInTheDocument();
  expect([...cache.values()].some((entry) => entry.data?.groups?.length)).toBe(
    false
  );
});

// Corrupt totals, privacy, coverage, or response grouping must never become a visible snapshot.
test.each([
  [
    "array category",
    { ...summary, groups: [{ ...summary.groups[0], category: ["USER"] }] },
  ],
  ["array status", { ...summary, status: ["ready"] }],
  [
    "numeric token",
    {
      ...summary,
      groups: [
        {
          ...summary.groups[0],
          totals: { ...totals, input_tokens: 1 },
        },
      ],
    },
  ],
  [
    "extra cost decimals",
    {
      ...summary,
      groups: [
        {
          ...summary.groups[0],
          totals: { ...totals, cost_cents: "1.1234567" },
        },
      ],
    },
  ],
  [
    "cache double count",
    {
      ...summary,
      groups: [
        {
          ...summary.groups[0],
          totals: { ...totals, total_tokens: "9007199254741004" },
        },
      ],
    },
  ],
  [
    "system incognito",
    { ...summary, groups: [{ ...summary.groups[2], incognito: true }] },
  ],
  [
    "pre-activation day",
    { ...summary, groups: [{ ...summary.groups[0], value: "2026-10-12" }] },
  ],
  ["wrong grouping", { ...summary, group_by: "model" }],
  [
    "trailing gap",
    {
      ...summary,
      coverage: { ...summary.coverage, to: "2026-10-13T00:00:00Z" },
    },
  ],
])("invalid %s response is unavailable", async (_reason, invalid) => {
  result = invalid as unknown as typeof summary;
  render(<UsageProbe />);
  expect(await screen.findByText("Unavailable")).toBeInTheDocument();
  expect(screen.queryByText(/total_tokens/)).not.toBeInTheDocument();
});

import OrgMeshUsagePage from "@/views/admin/OrgMeshUsagePage";
import {
  formatUsageInteger,
  formatUsageCostCents,
  usageDateQuery,
} from "@/lib/orgmesh-enterprise/usage";
import { NextIntlClientProvider } from "next-intl";
import chineseMessages from "@/i18n/messages/zh.json";
import { buildItems } from "@/lib/admin-sidebar-utils";
import { matchAdminRoute, type FeatureFlags } from "@/lib/admin-routes";
import { Tier } from "@/lib/settings/types";

// A float conversion would silently round these exact strings.
test.each([
  ["en", "9,007,199,254,740,993", "999,999,999,999.123456"],
  ["de", "9.007.199.254.740.993", "999.999.999.999,123456"],
  ["ar-u-nu-arab", "٩٬٠٠٧٬١٩٩٬٢٥٤٬٧٤٠٬٩٩٣", "٩٩٩٬٩٩٩٬٩٩٩٬٩٩٩٫١٢٣٤٥٦"],
])(
  "exact integer and six-place cents display in %s",
  (locale, integer, cost) => {
    expect(formatUsageInteger(totals.input_tokens, locale)).toBe(integer);
    expect(formatUsageCostCents(totals.cost_cents, locale)).toBe(cost);
  }
);

test("UTC date query includes today's mutable bucket and rejects dates outside the latest 90", () => {
  expect(
    usageDateQuery(
      "2026-10-13",
      "2026-10-13",
      "flow",
      new Date("2026-10-13T23:59:59Z")
    )
  ).toEqual({
    start: "2026-10-13T00:00:00Z",
    end: "2026-10-14T00:00:00Z",
    group_by: "flow",
  });
  expect(
    usageDateQuery("2026-07-15", "2026-10-13", "day", new Date("2026-10-13"))
  ).toBeUndefined();
  expect(
    usageDateQuery("2026-10-14", "2026-10-14", "day", new Date("2026-10-13"))
  ).toBeUndefined();
  expect(
    usageDateQuery("2026-02-30", "2026-10-13", "day", new Date("2026-10-13"))
  ).toBeUndefined();
});

test("dashboard displays separate actors, incognito, exact totals and source pricing notice", async () => {
  render(<OrgMeshUsagePage />);
  const list = await screen.findByRole("list", { name: "Usage groups" });
  expect(list).toHaveTextContent("User");
  expect(list).toHaveTextContent("Incognito user");
  expect(list).toHaveTextContent("Attributed system");
  expect(list).toHaveTextContent("Unattributed system");
  expect(list).toHaveTextContent("Total tokens: 9,007,199,254,740,998");
  expect(list).toHaveTextContent(
    "Estimated cost (USD cents): 999,999,999,999.123456"
  );
  expect(screen.getByText(/0 may mean missing pricing/)).toBeInTheDocument();
  expect(
    screen.getByText(/Current-day values are daily source aggregates/)
  ).toBeInTheDocument();
  expect(screen.queryByText(/grand total/i)).not.toBeInTheDocument();
  expect(screen.getByText(/Collection starts:/)).toHaveTextContent(
    "Oct 13, 2026"
  );
  expect(screen.getByText(/Published coverage/)).toHaveTextContent(
    "Oct 13, 2026"
  );
});

test("Chinese dashboard always shows the required unknown-pricing label", async () => {
  render(
    <NextIntlClientProvider locale="zh" messages={chineseMessages}>
      <OrgMeshUsagePage />
    </NextIntlClientProvider>
  );
  expect(await screen.findByText(/0可能表示缺少定价/)).toBeInTheDocument();
});

test("disabled usage hides query controls", async () => {
  usageEnabled = false;
  render(<OrgMeshUsagePage />);
  expect(await screen.findByText(/feature is disabled/i)).toBeInTheDocument();
  expect(screen.queryByLabelText("Start date (UTC)")).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Apply dates" })
  ).not.toBeInTheDocument();
  expect(
    fetchSpy.mock.calls.some(([url]) => String(url).includes("/usage/summary"))
  ).toBe(false);
});

test("dashboard distinguishes waiting, unavailable and a published empty snapshot", async () => {
  result = {
    ...summary,
    status: "waiting",
    coverage: null,
    published_at: null,
    revision: 0,
    groups: [],
  } as unknown as typeof summary;
  const user = setupUser();
  render(<OrgMeshUsagePage />);
  expect(
    await screen.findByText(/Waiting for the first full UTC day/)
  ).toBeInTheDocument();
  expect(
    screen.queryByText(/No usage in this published range/)
  ).not.toBeInTheDocument();
  result = {
    ...summary,
    status: "unavailable",
    coverage: null,
    published_at: null,
    revision: 0,
    groups: [],
  } as unknown as typeof summary;
  await user.click(screen.getByRole("button", { name: "Reload" }));
  expect(
    await screen.findByText(/No published usage snapshot/)
  ).toBeInTheDocument();
  result = { ...summary, groups: [] };
  await user.click(screen.getByRole("button", { name: "Reload" }));
  expect(
    await screen.findByText(/No usage in this published range/)
  ).toBeInTheDocument();
  expect(screen.getByText(/Published coverage/)).toBeInTheDocument();
});

test("date validation leaves the last query intact and group change uses a new query", async () => {
  const user = setupUser();
  render(<OrgMeshUsagePage />);
  await screen.findByRole("list", { name: "Usage groups" });
  const firstCalls = fetchSpy.mock.calls.filter(([url]) =>
    String(url).includes("/usage/summary")
  ).length;
  const start = screen.getByLabelText("Start date (UTC)");
  act(() => {
    fireEvent.change(start, { target: { value: "2026-01-01" } });
  });
  await user.click(screen.getByRole("button", { name: "Apply dates" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "most recent 90 UTC dates"
  );
  expect(
    fetchSpy.mock.calls.filter(([url]) =>
      String(url).includes("/usage/summary")
    )
  ).toHaveLength(firstCalls);
  act(() => {
    fireEvent.change(start, { target: { value: "2026-10-13" } });
  });
  await user.click(screen.getByRole("combobox", { name: "Group by" }));
  await user.click(screen.getByRole("option", { name: /^Model$/ }));
  result = {
    ...summary,
    group_by: "model",
    groups: [
      { value: "Example model", category: "USER", incognito: false, totals },
    ],
  };
  await user.click(screen.getByRole("button", { name: "Apply dates" }));
  expect(await screen.findByText("Example model")).toBeInTheDocument();
  const call = fetchSpy.mock.calls.find(([url]) =>
    String(url).includes("group_by=model")
  );
  expect(
    new URL(String(call?.[0]), "http://localhost").searchParams.get("start")
  ).toBe("2026-10-13T00:00:00Z");
  expect(
    new URL(String(call?.[0]), "http://localhost").searchParams.get("end")
  ).toBe("2026-10-14T00:00:00Z");
});

test("usage navigation requires full admin and an enabled capability", () => {
  const flags: FeatureFlags = {
    vectorDbEnabled: false,
    enableCloud: false,
    tier: Tier.COMMUNITY,
    customAnalyticsEnabled: false,
    hasSubscription: false,
    hooksEnabled: false,
    opensearchEnabled: false,
    queryHistoryEnabled: false,
    craftAvailable: false,
  };
  const path = "/admin/orgmesh-enterprise/usage";
  expect(matchAdminRoute(path)?.requiredPermission).toBe(
    Permission.FULL_ADMIN_PANEL_ACCESS
  );
  expect(
    buildItems([Permission.FULL_ADMIN_PANEL_ACCESS], flags, null).some(
      (item) => item.link === path
    )
  ).toBe(false);
  expect(
    buildItems(
      [Permission.FULL_ADMIN_PANEL_ACCESS],
      { ...flags, orgmeshUsageEnabled: true },
      null
    )
  ).toEqual(
    expect.arrayContaining([
      expect.objectContaining({ link: path, disabled: false }),
    ])
  );
  expect(
    buildItems(
      [Permission.MANAGE_USER_GROUPS],
      { ...flags, orgmeshUsageEnabled: true },
      null
    ).some((item) => item.link === path)
  ).toBe(false);
});

import { readFileSync } from "node:fs";
import { resolve } from "node:path";

test("shared summary fixture is accepted without changing its exact totals", async () => {
  const fixture = JSON.parse(
    readFileSync(
      resolve(
        process.cwd(),
        "../contracts/orgmesh-enterprise/fixtures/usage-summary.json"
      ),
      "utf8"
    )
  );
  result = fixture.summary;
  render(<UsageProbe />);
  expect(
    await screen.findByText(/"cost_cents":"0.123456"/)
  ).toBeInTheDocument();
  expect(screen.getByText(/"total_tokens":"15"/)).toBeInTheDocument();
});

test("six fractional cents remain visible, including leading zeros", () => {
  expect(formatUsageCostCents("0.000001", "en")).toBe("0.000001");
  expect(formatUsageCostCents("0.000000", "de")).toBe("0,000000");
});

test("non-admin users cannot obtain private usage context", async () => {
  mockAdmin = false;
  render(<OrgMeshUsagePage />);
  expect(
    await screen.findByText(/full administrator access is required/i)
  ).toBeInTheDocument();
  expect(
    fetchSpy.mock.calls.some(
      ([url]) =>
        String(url).endsWith("/context") ||
        String(url).includes("/usage/summary")
    )
  ).toBe(false);
});

test("usage request sends only the bounded query with no-store session credentials", async () => {
  render(<UsageProbe />);
  await screen.findByText(/9007199254740993/);
  const call = fetchSpy.mock.calls.find(([url]) =>
    String(url).includes("/usage/summary")
  );
  const params = new URL(String(call?.[0]), "http://localhost").searchParams;
  expect(Object.fromEntries(params)).toEqual({
    start: "2026-10-12T00:00:00Z",
    end: "2026-10-14T00:00:00Z",
    group_by: "day",
  });
  expect(call?.[1]).toEqual({ cache: "no-store", credentials: "include" });
});

describe("mounted usage refresh and publication age", () => {
  beforeEach(() => {
    jest.useFakeTimers();
    jest.setSystemTime(new Date(summary.published_at));
  });

  async function advance(milliseconds: number) {
    await act(async () => jest.advanceTimersByTimeAsync(milliseconds));
  }

  function summaryCalls() {
    return fetchSpy.mock.calls.filter(([url]) =>
      String(url).includes("/usage/summary")
    ).length;
  }

  // A pending request must not stop the independent publication-age clock.
  test("marks a ready publication stale after 120 seconds while its refresh hangs", async () => {
    render(<UsageProbe />);
    await screen.findByText(/9007199254740993/);
    const pending = deferred<Response>();
    const upstream = fetchSpy.getMockImplementation();
    fetchSpy.mockImplementation((url, init) =>
      String(url).includes("/usage/summary")
        ? pending.promise
        : upstream?.(url, init)
    );
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Refresh usage" }));
    });
    await advance(120_000 - (Date.now() - Date.parse(summary.published_at)));
    expect(screen.getByText("Current")).toBeInTheDocument();
    await advance(1);
    expect(screen.getByText("Stale")).toBeInTheDocument();
    expect(screen.getByText(/9007199254740993/)).toBeInTheDocument();
  });

  // The default query initially ends at collection_start, so polling alone is insufficient.
  test("rolls the untouched default window across UTC midnight from waiting to published", async () => {
    jest.setSystemTime(new Date("2026-10-12T23:59:50Z"));
    const boundary = Date.parse(summary.collection_start);
    const empty = {
      ...summary,
      coverage: null,
      published_at: null,
      revision: 0,
      groups: [],
    };
    const upstream = fetchSpy.getMockImplementation();
    fetchSpy.mockImplementation(async (url, init) => {
      if (!String(url).includes("/usage/summary")) return upstream?.(url, init);
      const end = new URL(String(url), "http://localhost").searchParams.get(
        "end"
      );
      // Match summaryBase: the old date range remains unavailable after activation.
      const snapshot =
        Date.now() < boundary
          ? { ...empty, status: "waiting" }
          : !end || Date.parse(end) <= boundary || Date.now() < boundary + 5_000
            ? { ...empty, status: "unavailable" }
            : { ...summary, published_at: "2026-10-13T00:00:05Z" };
      return new Response(JSON.stringify(snapshot));
    });
    render(<OrgMeshUsagePage />);
    await screen.findByText(/Waiting for the first full UTC day/);
    expect(screen.getByLabelText(/End date \(UTC/)).toHaveValue("2026-10-12");
    await advance(30_000);
    expect(
      screen.getByRole("list", { name: "Usage groups" })
    ).toHaveTextContent("9,007,199,254,740,998");
    expect(screen.getByLabelText(/End date \(UTC/)).toHaveValue("2026-10-13");
    const ends = fetchSpy.mock.calls
      .filter(([url]) => String(url).includes("/usage/summary"))
      .map(([url]) =>
        new URL(String(url), "http://localhost").searchParams.get("end")
      );
    expect(ends).toContain("2026-10-13T00:00:00Z");
    expect(ends).toContain("2026-10-14T00:00:00Z");
  });

  test("preserves a user-selected fixed date range across UTC midnight", async () => {
    jest.setSystemTime(new Date("2026-10-13T23:59:50Z"));
    render(<OrgMeshUsagePage />);
    await screen.findByRole("list", { name: "Usage groups" });
    await act(async () => {
      fireEvent.change(screen.getByLabelText("Start date (UTC)"), {
        target: { value: "2026-10-13" },
      });
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Apply dates" }));
    });
    await advance(30_000);
    expect(screen.getByLabelText("Start date (UTC)")).toHaveValue("2026-10-13");
    expect(screen.getByLabelText(/End date \(UTC/)).toHaveValue("2026-10-13");
    const calls = fetchSpy.mock.calls.filter(([url]) =>
      String(url).includes("/usage/summary")
    );
    expect(
      new URL(String(calls.at(-1)?.[0]), "http://localhost").searchParams.get(
        "start"
      )
    ).toBe("2026-10-13T00:00:00Z");
    expect(
      calls.every(
        ([url]) =>
          new URL(String(url), "http://localhost").searchParams.get("end") ===
          "2026-10-14T00:00:00Z"
      )
    ).toBe(true);
  });

  // SWR's built-in interval skips errors, so a failed refresh needs recovery too.
  test("automatically retries an outage and clears stale for a renewed publication", async () => {
    render(<UsageProbe />);
    await screen.findByText(/9007199254740993/);
    usageStatus = 503;
    await advance(15_000);
    expect(screen.getByText("Stale")).toBeInTheDocument();
    expect(screen.getByText(/9007199254740993/)).toBeInTheDocument();
    usageStatus = 200;
    result = {
      ...summary,
      published_at: new Date(Date.now()).toISOString(),
      revision: 8,
    };
    await advance(15_000);
    expect(screen.getByText("Current")).toBeInTheDocument();
    expect(screen.getByText(/"revision":8/)).toBeInTheDocument();
  });

  test("does not overlap a stalled automatic refresh and stops after unmount", async () => {
    const view = render(<UsageProbe />);
    await screen.findByText(/9007199254740993/);
    const pending = deferred<Response>();
    const upstream = fetchSpy.getMockImplementation();
    fetchSpy.mockImplementation((url, init) =>
      String(url).includes("/usage/summary")
        ? pending.promise
        : upstream?.(url, init)
    );
    await advance(15_000);
    expect(summaryCalls()).toBe(2);
    await advance(120_000);
    expect(screen.getByText("Stale")).toBeInTheDocument();
    expect(summaryCalls()).toBe(2);
    view.unmount();
    await act(async () =>
      pending.resolve(new Response(JSON.stringify(summary)))
    );
    await advance(150_000);
    expect(summaryCalls()).toBe(2);
  });

  test("a renewed publication resets the independent stale deadline", async () => {
    render(<UsageProbe />);
    await screen.findByText(/9007199254740993/);
    const pending = deferred<Response>();
    const upstream = fetchSpy.getMockImplementation();
    fetchSpy.mockImplementation((url, init) =>
      String(url).includes("/usage/summary")
        ? pending.promise
        : upstream?.(url, init)
    );
    await advance(120_001);
    expect(screen.getByText("Stale")).toBeInTheDocument();
    result = {
      ...summary,
      published_at: new Date(Date.now()).toISOString(),
      revision: 8,
    };
    await act(async () =>
      pending.resolve(new Response(JSON.stringify(result)))
    );
    expect(screen.getByText("Current")).toBeInTheDocument();
    const stalled = deferred<Response>();
    fetchSpy.mockImplementation((url, init) =>
      String(url).includes("/usage/summary")
        ? stalled.promise
        : upstream?.(url, init)
    );
    await advance(120_000);
    expect(screen.getByText("Current")).toBeInTheDocument();
    await advance(1);
    expect(screen.getByText("Stale")).toBeInTheDocument();
  });

  test("a summary authority failure hides data and stops automatic requests", async () => {
    render(<UsageProbe />);
    await screen.findByText(/9007199254740993/);
    usageStatus = 403;
    await advance(15_000);
    expect(screen.getByText("Unavailable")).toBeInTheDocument();
    expect(screen.queryByText(/9007199254740993/)).not.toBeInTheDocument();
    await advance(120_000);
    expect(summaryCalls()).toBe(2);
  });

  test("keeps refreshing when healthy responses contain unchanged data", async () => {
    render(<UsageProbe />);
    await screen.findByText(/9007199254740993/);
    for (let interval = 0; interval < 3; interval++) await advance(15_000);
    expect(summaryCalls()).toBe(4);
    expect(screen.getByText("Current")).toBeInTheDocument();
  });

  test("stops scheduled refresh when the capability becomes disabled", async () => {
    render(<UsageProbe />);
    await screen.findByText(/9007199254740993/);
    usageEnabled = false;
    await act(async () => {
      fireEvent.click(
        screen.getByRole("button", { name: "Verify capabilities" })
      );
    });
    expect(screen.queryByText(/9007199254740993/)).not.toBeInTheDocument();
    await advance(150_000);
    expect(summaryCalls()).toBe(1);
  });

  test("does not overlap a stalled initial request", async () => {
    const pending = deferred<Response>();
    const upstream = fetchSpy.getMockImplementation();
    fetchSpy.mockImplementation((url, init) =>
      String(url).includes("/usage/summary")
        ? pending.promise
        : upstream?.(url, init)
    );
    render(<UsageProbe />);
    await advance(150_000);
    expect(summaryCalls()).toBe(1);
    expect(screen.queryByText(/9007199254740993/)).not.toBeInTheDocument();
  });

  test("cancels scheduled refresh when the dashboard unmounts", async () => {
    const view = render(<UsageProbe />);
    await screen.findByText(/9007199254740993/);
    view.unmount();
    await advance(150_000);
    expect(summaryCalls()).toBe(1);
  });

  test.each(["disabled", "unauthorized"])(
    "never polls when %s",
    async (mode) => {
      usageEnabled = mode !== "disabled";
      mockAdmin = mode !== "unauthorized";
      render(<UsageProbe />);
      await advance(150_000);
      expect(summaryCalls()).toBe(0);
    }
  );

  test("stops automatic refresh when the current actor loses admin access", async () => {
    const view = render(<UsageProbe />);
    await screen.findByText(/9007199254740993/);
    mockAdmin = false;
    view.rerender(<UsageProbe />);
    expect(screen.queryByText(/9007199254740993/)).not.toBeInTheDocument();
    await advance(150_000);
    expect(summaryCalls()).toBe(1);
  });
});
