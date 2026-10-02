import {
  createDocumentRequest,
  downloadSavedDocument,
  isDocumentSnapshot,
} from "@/sections/workspace/documents/api";

const id = "10000000-0000-4000-8000-000000000001";
const version = "20000000-0000-4000-8000-000000000001";
const snapshot = {
  document_id: id,
  version_id: version,
  content_hash: "a".repeat(64),
  title: "Document.docx",
  project_id: null,
};
beforeEach(() => {
  globalThis.fetch = jest.fn();
});
afterEach(() => jest.restoreAllMocks());

test("creation retains the request key after a lost response", async () => {
  const fetcher = jest.mocked(fetch);
  fetcher
    .mockRejectedValueOnce(new Error("Network error"))
    .mockResolvedValueOnce({
      ok: true,
      json: async () => snapshot,
    } as Response);
  const request = createDocumentRequest("Document", null);
  await expect(request.submit()).rejects.toThrow();
  expect(await request.submit()).toEqual(snapshot);
  expect(fetcher.mock.calls[0]?.[1]?.headers).toEqual(
    fetcher.mock.calls[1]?.[1]?.headers
  );
  expect(fetcher.mock.calls[1]?.[1]?.body).toBe(
    fetcher.mock.calls[0]?.[1]?.body
  );
});

test("download first resolves the latest saved version and stops on missing access", async () => {
  const fetcher = jest
    .mocked(fetch)
    .mockResolvedValue({ ok: false, status: 404 } as Response);
  await expect(downloadSavedDocument(id)).rejects.toThrow();
  expect(fetcher).toHaveBeenCalledTimes(1);
  expect(fetcher.mock.calls[0]?.[0]).toBe(`/api/orgmesh/documents/${id}`);
});

test("snapshot validation rejects foreign shapes and invalid IDs", () => {
  expect(isDocumentSnapshot(snapshot)).toBe(true);
  expect(isDocumentSnapshot({ ...snapshot, document_id: "../secret" })).toBe(
    false
  );
  expect(isDocumentSnapshot({ ...snapshot, content_hash: "bad" })).toBe(false);
});

test("uses the committed save version even if another tab later saves", async () => {
  const fetcher = jest
    .mocked(fetch)
    .mockResolvedValue({ ok: false, status: 403 } as Response);
  await expect(
    downloadSavedDocument(id, undefined, snapshot)
  ).rejects.toThrow();
  expect(fetcher).toHaveBeenCalledTimes(1);
  expect(fetcher.mock.calls[0]?.[0]).toBe(
    `/api/orgmesh/documents/${id}/versions/${version}/content`
  );
});

test("rejects corrupt saved bytes before creating a download", async () => {
  const digest = jest.fn(async () => new Uint8Array(32).buffer);
  Object.defineProperty(crypto, "subtle", {
    configurable: true,
    value: { digest },
  });
  const objectUrl = jest.fn();
  URL.createObjectURL = objectUrl;
  jest
    .mocked(fetch)
    .mockResolvedValue({
      ok: true,
      arrayBuffer: async () => new Uint8Array([80, 75, 3, 4]).buffer,
    } as Response);
  await expect(downloadSavedDocument(id, undefined, snapshot)).rejects.toThrow(
    "CONTENT_HASH_MISMATCH"
  );
  expect(objectUrl).not.toHaveBeenCalled();
});
