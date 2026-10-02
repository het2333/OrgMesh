import React from "react";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import useSWR from "swr";
import { useUser } from "@/providers/UserProvider";
import { FetchError } from "@/lib/fetcher";
import PresentationHistory from "@/sections/workspace/presentations/PresentationHistory";

jest.mock("swr");
jest.mock("@/providers/UserProvider", () => ({ useUser: jest.fn() }));
jest.mock("next-intl", () => ({
  useTranslations: () => (key: string, values?: { page?: number }) =>
    values?.page ? `${key} ${values.page}` : key,
  useFormatter: () => ({ dateTime: () => "formatted date" }),
}));
jest.mock("@opal/components", () => ({
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
    as: Tag = "span",
    children,
    font: _font,
    color: _color,
    maxLines: _maxLines,
    ...props
  }: {
    as?: "span" | "h1" | "h2" | "h3" | "p";
    children: React.ReactNode;
    font?: string;
    color?: string;
    maxLines?: number;
  }) => <Tag {...props}>{children}</Tag>,
  IconLoader: () => <span aria-hidden="true" />,
}));
jest.mock("@opal/layouts", () => ({
  IllustrationContent: ({
    title,
    description,
  }: {
    title: string;
    description?: string;
  }) => (
    <div>
      <p>{title}</p>
      <p>{description}</p>
    </div>
  ),
}));
jest.mock("@opal/icons", () => ({
  SvgHistory: () => null,
  SvgRefreshCw: () => null,
  SvgSlidesFile: () => null,
  SvgBubbleText: () => null,
  SvgFolder: () => null,
  SvgArrowLeft: () => null,
  SvgArrowRight: () => null,
}));

const taskId = "12345678-1234-1234-1234-123456789abc";
const deckId = "aaaaaaaa-1234-1234-1234-123456789abc";
const sourceId = "bbbbbbbb-1234-1234-1234-123456789abc";
const task = {
  platform_task_id: taskId,
  task_id: taskId,
  presentation_id: deckId,
  status: "completed",
  project_id: 7,
  source_chat_id: sourceId,
  created_at: "2026-10-01T00:00:00Z",
  updated_at: "2026-10-01T00:01:00Z",
};
const deck = {
  id: deckId,
  title: "Owned deck",
  n_slides: 6,
  created_at: task.created_at,
  updated_at: task.updated_at,
  generation_mode: "general",
};
const mutate = jest.fn();
let tasks: unknown[] = [task];
let taskError: Error | undefined;
let loading = false;
let deckError: Error | undefined;
let liveError: Error | undefined;

beforeEach(() => {
  tasks = [task];
  taskError = undefined;
  deckError = undefined;
  liveError = undefined;
  loading = false;
  mutate.mockClear();
  jest.mocked(useUser).mockReturnValue({
    user: { id: "owner-a" },
    isUserLoading: false,
  } as ReturnType<typeof useUser>);
  jest.mocked(useSWR).mockImplementation((key) => {
    const url = Array.isArray(key) ? key[0] : "";
    if (typeof url === "string" && url.includes("/history?"))
      return {
        data: tasks,
        error: taskError,
        isLoading: loading,
        mutate,
      } as ReturnType<typeof useSWR>;
    if (url === "/api/orgmesh/presenton/presentations")
      return {
        data: [deck],
        error: deckError,
        isLoading: false,
        mutate,
      } as ReturnType<typeof useSWR>;
    if (url === "/api/orgmesh/presenton/jobs")
      return {
        data: [],
        error: liveError,
        isLoading: false,
        mutate,
      } as ReturnType<typeof useSWR>;
    return {
      data: [{ id: 7, name: "Owned project" }],
      isLoading: false,
      mutate,
    } as ReturnType<typeof useSWR>;
  });
});
afterEach(cleanup);

test("shows task status, deck title and verified source/project/editor links", () => {
  render(<PresentationHistory />);
  expect(screen.getByText("Owned deck")).toBeTruthy();
  expect(screen.getByText("status.completed")).toBeTruthy();
  expect(
    screen.getByRole("link", { name: "openSource" }).getAttribute("href")
  ).toBe(`/app?chatId=${sourceId}`);
  expect(
    screen.getByRole("link", { name: "Owned project" }).getAttribute("href")
  ).toBe("/app?projectId=7");
  expect(
    screen.getByRole("link", { name: "openEditor" }).getAttribute("href")
  ).toBe(`/app/tools/presentations/${deckId}`);
});

test("hides cached records and source links on auth denial from any source", () => {
  deckError = new FetchError("denied", 403, null);
  render(<PresentationHistory />);
  expect(screen.getByText("authTitle")).toBeTruthy();
  expect(screen.queryByText("Owned deck")).toBeNull();
  expect(screen.queryByRole("link", { name: "openSource" })).toBeNull();
});

test("handles disabled history without hiding legacy deck listing", () => {
  taskError = new FetchError("disabled", 404, null);
  render(<PresentationHistory />);
  expect(screen.getByText("disabledTitle")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "presentationsTab" }));
  expect(screen.getByText("Owned deck")).toBeTruthy();
});

test("renders loading, empty, error and retry states", () => {
  loading = true;
  const { rerender } = render(<PresentationHistory />);
  expect(screen.getByText("loading")).toBeTruthy();
  loading = false;
  tasks = [];
  rerender(<PresentationHistory />);
  expect(screen.getByText("emptyTasksTitle")).toBeTruthy();
  taskError = new FetchError("unavailable", 503, null);
  rerender(<PresentationHistory />);
  fireEvent.click(screen.getByRole("button", { name: "retry" }));
  expect(mutate).toHaveBeenCalled();
});

test("uses lookahead pagination and resets the offset on status filter change", () => {
  tasks = Array.from({ length: 21 }, (_, index) => ({
    ...task,
    platform_task_id: `${index}-${taskId}`,
  }));
  render(<PresentationHistory />);
  fireEvent.click(screen.getByRole("button", { name: "nextPage" }));
  expect(screen.getByText("pageNumber 2")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "filter.error" }));
  expect(screen.getByText("pageNumber 1")).toBeTruthy();
  expect(
    jest
      .mocked(useSWR)
      .mock.calls.some(
        ([key]) => Array.isArray(key) && String(key[0]).includes("status=error")
      )
  ).toBe(true);
});

test("does not invent missing provenance or show a source link for imported decks", () => {
  tasks = [{ ...task, source_chat_id: null, project_id: null }];
  render(<PresentationHistory />);
  expect(screen.queryByRole("link", { name: "openSource" })).toBeNull();
  expect(screen.queryByRole("link", { name: "Owned project" })).toBeNull();
});

test("keeps stored history when live engine status refresh fails", () => {
  liveError = new FetchError("offline", 503, null);
  render(<PresentationHistory />);
  expect(screen.getByText("liveUnavailable")).toBeTruthy();
  expect(screen.getByText("Owned deck")).toBeTruthy();
});

test("waits for owner resolution and does not request data using an old user", () => {
  jest.mocked(useUser).mockReturnValue({
    user: { id: "old-owner" },
    isUserLoading: true,
  } as ReturnType<typeof useUser>);
  render(<PresentationHistory />);
  expect(screen.getByText("loading")).toBeTruthy();
  expect(screen.queryByText("Owned deck")).toBeNull();
  expect(jest.mocked(useSWR).mock.calls.every(([key]) => key === null)).toBe(
    true
  );
});

test("uses a separate cache scope when the resolved owner changes", () => {
  const { rerender } = render(<PresentationHistory />);
  jest.mocked(useUser).mockReturnValue({
    user: { id: "owner-b" },
    isUserLoading: false,
  } as ReturnType<typeof useUser>);
  rerender(<PresentationHistory />);
  expect(
    jest
      .mocked(useSWR)
      .mock.calls.slice(-4)
      .every(([key]) => Array.isArray(key) && key[1] === "owner-b")
  ).toBe(true);
});

test("shows the unconfirmed warning without encouraging duplicate generation", () => {
  tasks = [{ ...task, status: "submitting", presentation_id: null }];
  render(<PresentationHistory />);
  expect(screen.getByText("unconfirmedHint")).toBeTruthy();
  expect(screen.queryByRole("link", { name: "openEditor" })).toBeNull();
});

test("resets task paging and status filter after the resolved owner changes", () => {
  tasks = Array.from({ length: 21 }, (_, index) => ({
    ...task,
    platform_task_id: `${index}-${taskId}`,
  }));
  const { rerender } = render(<PresentationHistory />);
  fireEvent.click(screen.getByRole("button", { name: "filter.error" }));
  fireEvent.click(screen.getByRole("button", { name: "nextPage" }));
  expect(screen.getByText("pageNumber 2")).toBeTruthy();
  jest.mocked(useUser).mockReturnValue({
    user: { id: "owner-b" },
    isUserLoading: false,
  } as ReturnType<typeof useUser>);
  rerender(<PresentationHistory />);
  expect(screen.getByText("pageNumber 1")).toBeTruthy();
  const latest = jest.mocked(useSWR).mock.calls.slice(-4)[0]?.[0];
  expect(Array.isArray(latest) ? latest[0] : "").toBe(
    "/api/orgmesh/presenton/history?limit=21&offset=0"
  );
});
