import React from "react";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import useSWR from "swr";
import DocumentEditor from "@/sections/workspace/documents/DocumentEditor";
import { downloadSavedDocument } from "@/sections/workspace/documents/api";

jest.mock("swr");
jest.mock("@/providers/UserProvider", () => ({
  useUser: () => ({ user: { id: "owner" }, isUserLoading: false }),
}));
jest.mock("next-intl", () => ({
  useTranslations: () => (key: string) => key,
  useLocale: () => "zh",
}));
jest.mock("@/sections/workspace/documents/api", () => ({
  ...jest.requireActual("@/sections/workspace/documents/api"),
  downloadSavedDocument: jest.fn(),
}));
jest.mock("@opal/components", () => ({
  Button: ({
    children,
    href,
    icon: _icon,
    prominence: _prominence,
    ...props
  }: React.ComponentProps<"button"> & {
    href?: string;
    icon?: unknown;
    prominence?: string;
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
    children: React.ReactNode;
    as?: "span" | "p";
    font?: string;
    color?: string;
  }) => <Tag {...props}>{children}</Tag>,
  IconLoader: () => <span />,
}));
jest.mock("@opal/icons", () => ({
  SvgArrowLeft: () => null,
  SvgDownload: () => null,
  SvgUploadCloud: () => null,
}));
const id = "10000000-0000-4000-8000-000000000001";
const doc = {
  document_id: id,
  version_id: id,
  content_hash: "a".repeat(64),
  title: "Saved.docx",
  project_id: null,
};
beforeEach(() => {
  jest.mocked(useSWR).mockImplementation(
    (key: unknown) =>
      ({
        data: String(key).includes("status") ? { enabled: true } : doc,
        isLoading: false,
        isValidating: false,
        error: undefined,
      }) as ReturnType<typeof useSWR>
  );
});
afterEach(() => {
  cleanup();
  jest.clearAllMocks();
});
function mount(save: () => Promise<boolean>, dirty = false) {
  render(<DocumentEditor id={id} />);
  const frame = screen.getByTitle("editorTitle") as HTMLIFrameElement;
  Object.defineProperty(frame.contentWindow, "orgmeshDocs", {
    configurable: true,
    value: { save, hasUnsavedChanges: () => dirty, getSnapshot: () => doc },
  });
  fireEvent.load(frame);
  return frame;
}
test("embeds the same-origin original renderer with document and locale", () => {
  const frame = mount(async () => true);
  expect(frame.getAttribute("src")).toBe(
    `/office/docs/index.html?document_id=${id}&lang=zh`
  );
});
test("persists through the original editor before downloading saved server bytes", async () => {
  const save = jest.fn(async () => true);
  mount(save);
  fireEvent.click(screen.getByRole("button", { name: "download" }));
  await waitFor(() => expect(downloadSavedDocument).toHaveBeenCalled());
  expect(save).toHaveBeenCalledTimes(1);
});
test("does not download when saving fails", async () => {
  mount(async () => false);
  fireEvent.click(screen.getByRole("button", { name: "download" }));
  await waitFor(() =>
    expect(screen.getByRole("alert").textContent).toBe("saveError")
  );
  expect(downloadSavedDocument).not.toHaveBeenCalled();
});
test("cancelled leave keeps the editor in place", () => {
  mount(async () => true, true);
  const confirm = jest.spyOn(window, "confirm").mockReturnValue(false);
  expect(fireEvent.click(screen.getByRole("link", { name: "back" }))).toBe(
    false
  );
  expect(confirm).toHaveBeenCalledTimes(1);
  expect(screen.getByTitle("editorTitle")).toBeTruthy();
  confirm.mockRestore();
});
