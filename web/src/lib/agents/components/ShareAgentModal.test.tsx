import React, { useEffect } from "react";
import { render, screen, setupUser, waitFor } from "@tests/setup/test-utils";
import {
  ShareAgentModal,
  type ShareAgentModalProps,
} from "@/lib/agents/components/ShareAgentModal";
import { useCreateModal } from "@opal/components";
import { Permission } from "@/lib/types";
import { SWR_KEYS } from "@/lib/swr-keys";

let mockCanManageAgents = false;

jest.mock("@/hooks/useShareableUsers", () => ({
  __esModule: true,
  default: jest.fn(() => ({
    data: [
      {
        email: "owner@example.com",
        id: "owner-id",
      },
    ],
  })),
}));

jest.mock("@/providers/UserProvider", () => ({
  useUser: jest.fn(() => ({
    isAdmin: false,
    user: { id: "owner-id", email: "owner@example.com" },
    adminCapabilities: mockCanManageAgents ? [Permission.MANAGE_AGENTS] : [],
  })),
}));

jest.mock("@/lib/agents/hooks", () => ({
  useAgent: jest.fn(() => ({
    agent: {
      admin_count: 1,
      attached_document_count: 0,
      builtin_persona: false,
      datetime_aware: false,
      default_model_configuration_id: null,
      description: "Test agent",
      display_priority: null,
      document_sets: [],
      group_shares: [],
      groups: [],
      hierarchy_node_count: 0,
      id: 101,
      is_featured: false,
      is_listed: true,
      is_public: false,
      labels: [],
      name: "Demo Agent",
      owner: {
        email: "owner@example.com",
        id: "owner-id",
      },
      owner_group: null,
      ownership_vacant: false,
      public_permission: "VIEWER",
      replace_base_system_prompt: false,
      search_start_date: null,
      sharing_status: "PRIVATE",
      starter_messages: null,
      system_prompt: null,
      task_prompt: null,
      tool_ids: [],
      tools: [],
      uploaded_image_id: undefined,
      user_file_ids: [],
      user_permission: "OWNER",
      user_shares: [],
      users: [],
    },
  })),
  useLabels: jest.fn(() => ({
    createLabel: jest.fn(),
    labels: [],
  })),
}));

function ModalHarness(props: ShareAgentModalProps) {
  const modal = useCreateModal();

  useEffect(() => {
    modal.toggle(true);
  }, [modal]);

  return (
    <modal.Provider>
      <ShareAgentModal {...props} />
    </modal.Provider>
  );
}

function renderShareAgentModal(overrides: Partial<ShareAgentModalProps> = {}) {
  const props: ShareAgentModalProps = {
    agentId: 101,
    groupIds: [],
    isFeatured: false,
    isPublic: false,
    labelIds: [],
    userIds: [],
    ...overrides,
  };

  return render(<ModalHarness {...props} />);
}

describe("ShareAgentModal", () => {
  it("renders the new share view", async () => {
    renderShareAgentModal();

    expect(await screen.findByText(/Share/)).toBeInTheDocument();
    expect(
      screen.getByPlaceholderText("Add users, groups, and accounts")
    ).toBeInTheDocument();
    expect(screen.getByText("Admins")).toBeInTheDocument();
    expect(screen.getByText("Only those invited")).toBeInTheDocument();
  });
});

let fetchSpy: jest.SpyInstance;
let legacyEnabled = true;
beforeEach(() => {
  mockCanManageAgents = false;
  legacyEnabled = true;
  fetchSpy = jest.spyOn(global, "fetch").mockImplementation(async (url) => {
    // Explicit legacy capability and policy, then the existing shareable-groups endpoint.
    if (url === SWR_KEYS.settings)
      return new Response(
        JSON.stringify({ ee_features_enabled: legacyEnabled })
      );
    if (url === SWR_KEYS.enterpriseSettings) return new Response("{}");
    if (url === SWR_KEYS.shareableGroups)
      return new Response(JSON.stringify([{ id: 7, name: "Research" }]));
    // Real updateAgentShares serializes the PATCH request used below.
    if (url === "/api/persona/101/share") return new Response("{}");
    return new Response("{}", { status: 503 });
  });
});
afterEach(() => fetchSpy.mockRestore());

// The modal must pass the enabled capability to the real share serializer.
test("enabled group sharing sends selected group_shares with their permission", async () => {
  mockCanManageAgents = true;
  const user = setupUser();
  renderShareAgentModal();
  await user.type(
    await screen.findByPlaceholderText("Add users, groups, and accounts"),
    "Research"
  );
  await user.click(await screen.findByRole("button", { name: /Research/ }));
  await user.click(screen.getByRole("button", { name: /^Save$/ }));
  await waitFor(() =>
    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/persona/101/share",
      expect.objectContaining({ method: "PATCH" })
    )
  );
  const request = fetchSpy.mock.calls.find(
    ([url]) => url === "/api/persona/101/share"
  );
  expect(JSON.parse(request?.[1].body)).toEqual(
    expect.objectContaining({
      group_shares: [{ group_id: 7, permission: "VIEWER" }],
    })
  );
});

test("an owner without MANAGE_AGENTS cannot select a group", async () => {
  const user = setupUser();
  renderShareAgentModal();
  await user.type(
    await screen.findByPlaceholderText("Add users, groups, and accounts"),
    "Research"
  );
  await waitFor(() =>
    expect(fetchSpy).toHaveBeenCalledWith(SWR_KEYS.shareableGroups)
  );
  expect(
    screen.queryByRole("button", { name: /Research/ })
  ).not.toBeInTheDocument();
});

test("disabled sharing does not probe the legacy policy or group endpoints", async () => {
  legacyEnabled = false;
  mockCanManageAgents = true;
  const user = setupUser();
  renderShareAgentModal();
  await user.type(
    await screen.findByPlaceholderText("Add users, groups, and accounts"),
    "Research"
  );
  expect(
    screen.queryByRole("button", { name: /Research/ })
  ).not.toBeInTheDocument();
  expect(
    fetchSpy.mock.calls.some(
      ([url]) =>
        url === SWR_KEYS.enterpriseSettings || url === SWR_KEYS.shareableGroups
    )
  ).toBe(false);
});
