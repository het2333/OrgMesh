import React from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useSearchParams } from "next/navigation";
import PeopleWorkspace from "@/sections/workspace/people/PeopleWorkspace";

let params = new URLSearchParams();
const push = jest.fn();
let loading = false;
let error: Error | undefined;
const retry = jest.fn();
const employees = [
  {
    employee_id: "alice",
    email: "alice@example.com",
    display_name: "Same Name",
    job_title: "Engineer",
    avatar_url: null,
    manager_id: null,
    direct_department_ids: ["team"],
    departments: [{ department_id: "team", name: "Platform", parent_id: null }],
  },
  {
    employee_id: "bob",
    email: "bob@example.com",
    display_name: "Same Name",
    job_title: null,
    avatar_url: null,
    manager_id: null,
    direct_department_ids: ["team"],
    departments: [],
  },
];
let items = employees;

jest.mock(
  "next/navigation",
  () => ({
    useSearchParams: jest.fn(),
    usePathname: () => "/app/people",
    useRouter: () => ({ push }),
  }),
  { virtual: true }
);
jest.mock(
  "next-intl",
  () => ({
    useTranslations: () => (key: string) => key,
    useFormatter: () => ({ number: (value: number) => String(value) }),
  }),
  { virtual: true }
);
jest.mock("@/lib/people/hooks", () => ({
  usePeople: () => ({
    data: loading
      ? undefined
      : { items, total: items.length, offset: 0, limit: 20 },
    isLoading: loading,
    error,
    mutate: retry,
  }),
  usePerson: (id: string) => ({
    data: employees.find((person) => person.employee_id === id),
    isLoading: false,
    error: undefined,
    mutate: retry,
  }),
  useTeams: () => ({
    data: {
      items: [
        {
          department_id: "team",
          name: "Platform",
          parent_id: null,
          member_count: 2,
        },
      ],
      total: 1,
      offset: 0,
      limit: 100,
    },
    isLoading: false,
    error: undefined,
    mutate: retry,
  }),
  useTeam: () => ({
    data: {
      department_id: "team",
      name: "Platform",
      member_count: 2,
      members: { items: employees, total: 2, offset: 0, limit: 20 },
    },
    isLoading: false,
    error: undefined,
    mutate: retry,
  }),
  useRelationships: () => ({
    data: {
      manager: null,
      direct_reports: [],
      total_reports: 0,
      offset: 0,
      limit: 20,
      warnings: ["manager_unavailable"],
    },
    isLoading: false,
    error: undefined,
    mutate: retry,
  }),
}));
jest.mock(
  "@opal/components",
  () => ({
    Button: ({
      children,
      href,
      icon: _icon,
      prominence: _prominence,
      size: _size,
      tooltip: _tooltip,
      ...props
    }: React.ComponentProps<"button"> & {
      href?: string;
      icon?: unknown;
      prominence?: string;
      size?: string;
      tooltip?: string;
    }) =>
      href ? (
        <a href={href}>{children}</a>
      ) : (
        <button {...props}>{children}</button>
      ),
    Text: ({
      children,
      as: Tag = "span",
      font: _font,
      color: _color,
      ...props
    }: {
      children?: React.ReactNode;
      as?: "span" | "h1" | "h2" | "p";
      font?: string;
      color?: string;
    }) => <Tag {...props}>{children}</Tag>,
    InputTypeIn: ({
      searchIcon: _icon,
      ...props
    }: React.ComponentProps<"input"> & { searchIcon?: boolean }) => (
      <input {...props} />
    ),
    IconLoader: () => <span />,
  }),
  { virtual: true }
);
jest.mock(
  "@opal/layouts",
  () => ({
    IllustrationContent: ({
      title,
      description,
    }: {
      title: string;
      description: string;
    }) => (
      <div>
        <p>{title}</p>
        <p>{description}</p>
      </div>
    ),
  }),
  { virtual: true }
);
jest.mock(
  "@opal/icons",
  () => ({
    SvgUsers: () => null,
    SvgUser: () => null,
    SvgSearch: () => null,
    SvgArrowLeft: () => null,
    SvgArrowRight: () => null,
    SvgRefreshCw: () => null,
    SvgChevronDown: () => null,
    SvgChevronUp: () => null,
  }),
  { virtual: true }
);

beforeEach(() => {
  params = new URLSearchParams();
  items = employees;
  loading = false;
  error = undefined;
  push.mockClear();
  retry.mockClear();
  jest
    .mocked(useSearchParams)
    .mockImplementation(() => params as ReturnType<typeof useSearchParams>);
});
afterEach(cleanup);

test("employee directory keeps duplicate names linked by distinct IDs", () => {
  render(<PeopleWorkspace />);
  const links = screen.getAllByRole("link", { name: "Same Name" });
  expect(links.map((link) => link.getAttribute("href"))).toEqual([
    "/app/people?person=alice",
    "/app/people?person=bob",
  ]);
  expect(screen.getByRole("button", { name: "tabs.teams" })).toBeTruthy();
  expect(screen.getByRole("button", { name: "tabs.chart" })).toBeTruthy();
});

test("search and department selection navigate through URL state", () => {
  render(<PeopleWorkspace />);
  fireEvent.change(screen.getByRole("textbox", { name: "search.label" }), {
    target: { value: "Li" },
  });
  fireEvent.submit(screen.getByRole("search"));
  expect(push).toHaveBeenCalledWith("/app/people?q=Li", { scroll: false });
  fireEvent.click(screen.getByRole("button", { name: "Platform" }));
  expect(push).toHaveBeenCalledWith("/app/people?department=team", {
    scroll: false,
  });
});

test("Back and Forward query changes restore the search field", () => {
  params = new URLSearchParams("q=First");
  const view = render(<PeopleWorkspace />);
  expect(
    screen.getByRole("textbox", { name: "search.label" }).getAttribute("value")
  ).toBe("First");
  params = new URLSearchParams("q=Second");
  view.rerender(<PeopleWorkspace />);
  expect(
    screen.getByRole("textbox", { name: "search.label" }).getAttribute("value")
  ).toBe("Second");
});

test("loading empty and error states do not invent employees", () => {
  loading = true;
  const view = render(<PeopleWorkspace />);
  expect(screen.getByRole("status")).toBeTruthy();
  loading = false;
  items = [];
  view.rerender(<PeopleWorkspace />);
  expect(screen.getByText("empty.title")).toBeTruthy();
  error = new Error("unavailable");
  view.rerender(<PeopleWorkspace />);
  fireEvent.click(screen.getByRole("button", { name: "retry" }));
  expect(retry).toHaveBeenCalledTimes(1);
});

test("profile shows unavailable manager and a normal knowledge search link", () => {
  params = new URLSearchParams("person=alice");
  render(<PeopleWorkspace />);
  expect(screen.getByText("managerUnavailable")).toBeTruthy();
  expect(
    screen.getByRole("link", { name: "knowledgeSearch" }).getAttribute("href")
  ).toBe("/app/search?q=Same+Name");
});

test("team and graph tabs render selected real directory identities", () => {
  params = new URLSearchParams("tab=teams&department=team");
  const view = render(<PeopleWorkspace />);
  expect(screen.getAllByText("Same Name").length).toBeGreaterThan(0);
  params = new URLSearchParams("tab=chart&person=alice");
  view.rerender(<PeopleWorkspace />);
  expect(screen.getByText("managerUnavailable")).toBeTruthy();
});
