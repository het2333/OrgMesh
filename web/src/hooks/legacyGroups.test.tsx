import { Text } from "@opal/components";
import {
  act,
  deferred,
  render,
  screen,
  waitFor,
} from "@tests/setup/test-utils";
import useGroups from "@/hooks/useGroups";
import useShareableGroups from "@/hooks/useShareableGroups";
import { useUserGroups } from "@/lib/hooks";
import { SWR_KEYS } from "@/lib/swr-keys";

jest.mock("next/navigation", () => ({
  usePathname: () => "/app",
  useRouter: () => ({ push: jest.fn(), back: jest.fn(), refresh: jest.fn() }),
}));

function GroupSelectors() {
  const groups = useGroups();
  const defaults = useGroups(true);
  const shareable = useShareableGroups();
  const users = useUserGroups();
  return (
    <>
      <Text as="p">{`Groups: ${JSON.stringify(groups.data)}`}</Text>
      <Text as="p">{`Defaults: ${JSON.stringify(defaults.data)}`}</Text>
      <Text as="p">{`Shareable: ${JSON.stringify(shareable.data)}`}</Text>
      <Text as="p">{`Users: ${JSON.stringify(users.data)}`}</Text>
      <Text as="p">{`Loading: ${[groups, defaults, shareable, users].every((state) => state.isLoading)}`}</Text>
    </>
  );
}

let enabled = true;
let policyStatus = 200;
let fetchSpy: jest.SpyInstance;
beforeEach(() => {
  enabled = true;
  policyStatus = 200;
  fetchSpy = jest.spyOn(global, "fetch").mockImplementation(async (url) => {
    // Core settings explicitly enable the existing legacy group feature.
    if (url === SWR_KEYS.settings)
      return new Response(JSON.stringify({ ee_features_enabled: enabled }));
    if (url === SWR_KEYS.enterpriseSettings)
      return new Response("{}", { status: policyStatus });
    if (url === SWR_KEYS.adminUserGroupsWithDefault)
      return new Response(JSON.stringify([{ id: 1, name: "Admin" }]));
    if (url === SWR_KEYS.adminUserGroups || url === SWR_KEYS.shareableGroups)
      return new Response(JSON.stringify([{ id: 7, name: "Research" }]));
    // Independent branding can be unavailable without disabling group access.
    return new Response("{}", { status: 503 });
  });
});
afterEach(() => fetchSpy.mockRestore());

// A permanent null useSettings().enterprise disables all three legacy selectors.
test("enabled selectors retain admin, default and shareable groups", async () => {
  render(<GroupSelectors />);
  expect(
    await screen.findByText('Groups: [{"id":7,"name":"Research"}]')
  ).toBeInTheDocument();
  expect(
    await screen.findByText('Defaults: [{"id":1,"name":"Admin"}]')
  ).toBeInTheDocument();
  expect(
    await screen.findByText('Shareable: [{"id":7,"name":"Research"}]')
  ).toBeInTheDocument();
  expect(
    await screen.findByText('Users: [{"id":7,"name":"Research"}]')
  ).toBeInTheDocument();
});

test("disabled selectors do not probe legacy policy or group endpoints", async () => {
  enabled = false;
  render(<GroupSelectors />);
  await waitFor(() =>
    expect(screen.getByText("Groups: []")).toBeInTheDocument()
  );
  expect(screen.getByText("Shareable: []")).toBeInTheDocument();
  expect(screen.getByText("Users: []")).toBeInTheDocument();
  expect(
    fetchSpy.mock.calls.some(
      ([url]) =>
        String(url).includes("enterprise-settings") ||
        String(url).includes("user-group")
    )
  ).toBe(false);
});

test("a failed legacy policy never enables group queries", async () => {
  policyStatus = 503;
  render(<GroupSelectors />);
  await waitFor(() =>
    expect(fetchSpy).toHaveBeenCalledWith(SWR_KEYS.enterpriseSettings)
  );
  expect(screen.queryByText(/Research/)).not.toBeInTheDocument();
  expect(
    fetchSpy.mock.calls.some(([url]) => String(url).includes("user-group"))
  ).toBe(false);
});

// The adapter must preserve the selectors' pending state while core enablement loads.
test("selectors remain pending until core settings resolve", async () => {
  const pending = deferred<Response>();
  const upstream = fetchSpy.getMockImplementation();
  fetchSpy.mockImplementation((url, init) =>
    url === SWR_KEYS.settings ? pending.promise : upstream?.(url, init)
  );
  render(<GroupSelectors />);
  expect(screen.getByText("Loading: true")).toBeInTheDocument();
  await act(async () =>
    pending.resolve(new Response(JSON.stringify({ ee_features_enabled: true })))
  );
  expect(
    await screen.findByText('Groups: [{"id":7,"name":"Research"}]')
  ).toBeInTheDocument();
});
