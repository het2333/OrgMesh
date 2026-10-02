import React from "react";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import useSWR from "swr";
import { useUser } from "@/providers/UserProvider";
import DocumentLibrary from "@/sections/workspace/documents/DocumentLibrary";
import { openDocumentEditor } from "@/sections/workspace/documents/api";

jest.mock("swr");
jest.mock("@/providers/UserProvider", () => ({ useUser: jest.fn() }));
jest.mock("next-intl", () => ({ useTranslations: () => (key: string) => key }));
jest.mock("@/sections/workspace/documents/api", () => ({
  ...jest.requireActual("@/sections/workspace/documents/api"),
  openDocumentEditor: jest.fn(),
}));
jest.mock("@opal/components", () => ({
  Button: ({
    children,
    icon: _icon,
    prominence: _prominence,
    ...props
  }: React.ComponentProps<"button"> & {
    icon?: unknown;
    prominence?: string;
  }) => <button {...props}>{children}</button>,
  Text: ({
    children,
    as: Tag = "span",
    font: _font,
    color: _color,
    ...props
  }: {
    children: React.ReactNode;
    as?: "span" | "h2" | "p";
    font?: string;
    color?: string;
  }) => <Tag {...props}>{children}</Tag>,
  InputTypeIn: (props: React.ComponentProps<"input">) => <input {...props} />,
  IconLoader: () => <span />,
}));
jest.mock("@opal/icons", () => ({
  SvgFileText: () => null,
  SvgPlus: () => null,
  SvgUploadCloud: () => null,
  SvgRefreshCw: () => null,
  SvgDownload: () => null,
}));
const id = "10000000-0000-4000-8000-000000000001";
const doc = {
  document_id: id,
  version_id: "20000000-0000-4000-8000-000000000001",
  content_hash: "a".repeat(64),
  title: "Saved.docx",
  project_id: null,
};
let enabled = false;
let owner: string | undefined = "owner";
beforeEach(() => {
  enabled = false;
  owner = "owner";
  jest.mocked(useUser).mockImplementation(
    () =>
      ({
        user: owner ? { id: owner } : null,
        isUserLoading: false,
      }) as ReturnType<typeof useUser>
  );
  jest.mocked(useSWR).mockImplementation(
    (key: unknown) =>
      ({
        data: !key
          ? undefined
          : String(key).includes("status")
            ? { enabled }
            : [doc],
        mutate: jest.fn(),
        isLoading: false,
        isValidating: false,
        error: undefined,
      }) as ReturnType<typeof useSWR>
  );
  globalThis.fetch = jest.fn();
});
afterEach(cleanup);

test("does not expose unfinished Word functions while disabled", () => {
  const { container } = render(<DocumentLibrary />);
  expect(container.innerHTML).toBe("");
});

test("loads owner-scoped saved documents only when enabled", () => {
  enabled = true;
  render(<DocumentLibrary />);
  expect(screen.getByText("Saved.docx")).toBeTruthy();
  expect(
    jest
      .mocked(useSWR)
      .mock.calls.some(
        ([key]) =>
          Array.isArray(key) &&
          key.includes("owner") &&
          key[0] === "/api/orgmesh/documents"
      )
  ).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: "open" }));
  expect(openDocumentEditor).toHaveBeenCalledWith(id);
});

test("blocks duplicate create clicks and opens the server-created document", async () => {
  enabled = true;
  let resolve!: (response: Response) => void;
  jest.mocked(fetch).mockReturnValue(
    new Promise((done) => {
      resolve = done;
    })
  );
  render(<DocumentLibrary />);
  const create = screen.getByRole("button", { name: "create" });
  fireEvent.click(create);
  fireEvent.click(create);
  expect(fetch).toHaveBeenCalledTimes(1);
  resolve({ ok: true, json: async () => doc } as Response);
  await waitFor(() => expect(openDocumentEditor).toHaveBeenCalledWith(id));
});

test("hides old cached files after logout", () => {
  enabled = true;
  const { rerender, container } = render(<DocumentLibrary />);
  owner = undefined;
  rerender(<DocumentLibrary />);
  expect(container.innerHTML).toBe("");
});

test("does not navigate to the prior owner's document after account change", async () => {
  enabled = true;
  let resolve!: (response: Response) => void;
  jest.mocked(fetch).mockReturnValue(
    new Promise((done) => {
      resolve = done;
    })
  );
  const { rerender } = render(<DocumentLibrary />);
  fireEvent.click(screen.getByRole("button", { name: "create" }));
  owner = "other-owner";
  rerender(<DocumentLibrary />);
  resolve({ ok: true, json: async () => doc } as Response);
  await waitFor(() => expect(jest.mocked(fetch).mock.results).toHaveLength(1));
  await new Promise((done) => setTimeout(done, 0));
  expect(openDocumentEditor).not.toHaveBeenCalled();
});

test("rejects oversized input before upload", () => {
  enabled = true;
  render(<DocumentLibrary />);
  const file = new File(["test"], "test.docx");
  Object.defineProperty(file, "size", { value: 20 * 1024 * 1024 + 1 });
  fireEvent.change(screen.getByLabelText("import"), {
    target: { files: [file] },
  });
  expect(screen.getByRole("alert").textContent).toBe("fileError");
  expect(fetch).not.toHaveBeenCalled();
});

test("lets users clear an imported file before creating a blank document", () => {
  enabled = true;
  render(<DocumentLibrary />);
  fireEvent.change(screen.getByLabelText("import"), {
    target: { files: [new File(["test"], "input.docx")] },
  });
  expect(screen.getByRole("button", { name: "importOpen" })).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "clearFile" }));
  expect(screen.getByRole("button", { name: "create" })).toBeTruthy();
});
