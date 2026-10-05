import React from "react";
import { act, renderHook, waitFor } from "@testing-library/react";
import { SWRConfig } from "swr";
import { usePeople } from "@/lib/people/hooks";
import { knowledgeHref } from "@/lib/people/types";

let owner = "first-owner";
jest.mock("@/providers/UserProvider", () => ({
  useUser: () => ({ user: { id: owner }, isUserLoading: false }),
}));

function wrapper({ children }: { children: React.ReactNode }) {
  return (
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
      {children}
    </SWRConfig>
  );
}

function response(id: string) {
  return {
    ok: true,
    status: 200,
    json: async () => ({
      items: [{ employee_id: id }],
      total: 1,
      offset: 0,
      limit: 20,
    }),
  } as Response;
}

afterEach(() => {
  jest.restoreAllMocks();
  owner = "first-owner";
});

test("an older query response cannot replace newer search results", async () => {
  let resolveOld: (value: Response) => void = () => {};
  global.fetch = jest.fn().mockImplementation((url: string) =>
    url.includes("q=old")
      ? new Promise<Response>((resolve) => {
          resolveOld = resolve;
        })
      : Promise.resolve(response("new-person"))
  );
  const view = renderHook(({ query }) => usePeople(query, null, 0), {
    initialProps: { query: "old" },
    wrapper,
  });
  await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(1));
  view.rerender({ query: "new" });
  await waitFor(() =>
    expect(view.result.current.data?.items[0]?.employee_id).toBe("new-person")
  );
  await act(async () => {
    resolveOld(response("old-person"));
  });
  expect(view.result.current.data?.items[0]?.employee_id).toBe("new-person");
});

test("owner changes never reuse another owner's directory cache", async () => {
  global.fetch = jest
    .fn()
    .mockResolvedValueOnce(response("first-person"))
    .mockImplementation(() => new Promise(() => {}));
  const view = renderHook(() => usePeople("", null, 0), { wrapper });
  await waitFor(() =>
    expect(view.result.current.data?.items[0]?.employee_id).toBe("first-person")
  );
  owner = "second-owner";
  view.rerender();
  expect(view.result.current.data).toBeUndefined();
});

test("missing work contact uses the employee ID for knowledge search", () => {
  expect(
    knowledgeHref({
      employee_id: "stable-id",
      display_name: null,
      email: null,
      job_title: null,
      avatar_url: null,
      manager_id: null,
      direct_department_ids: [],
      departments: [],
    })
  ).toBe("/app/search?q=stable-id");
});
