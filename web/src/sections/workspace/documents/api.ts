export const DOCUMENTS_API = "/api/orgmesh/documents";
export const MAX_DOCUMENT_BYTES = 20 * 1024 * 1024;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export interface DocumentSnapshot {
  document_id: string;
  version_id: string;
  content_hash: string;
  title: string;
  project_id: null;
}

export function isDocumentId(value: string): boolean {
  return UUID.test(value);
}

export function isDocumentSnapshot(value: unknown): value is DocumentSnapshot {
  return (
    typeof value === "object" &&
    value !== null &&
    "document_id" in value &&
    typeof value.document_id === "string" &&
    isDocumentId(value.document_id) &&
    "version_id" in value &&
    typeof value.version_id === "string" &&
    isDocumentId(value.version_id) &&
    "content_hash" in value &&
    typeof value.content_hash === "string" &&
    /^[a-f0-9]{64}$/.test(value.content_hash) &&
    "title" in value &&
    typeof value.title === "string" &&
    "project_id" in value &&
    value.project_id === null
  );
}

async function readSnapshot(response: Response): Promise<DocumentSnapshot> {
  if (!response.ok) throw new Error("DOCUMENT_REQUEST_FAILED");
  const result: unknown = await response.json();
  if (!isDocumentSnapshot(result)) throw new Error("INVALID_DOCUMENT_RESPONSE");
  return result;
}

export function createDocumentRequest(title: string, file: File | null) {
  const body = new FormData();
  body.set("title", title.trim());
  if (file) body.set("file", file);
  const key = crypto.randomUUID();
  return {
    async submit(): Promise<DocumentSnapshot> {
      return readSnapshot(
        await fetch(DOCUMENTS_API, {
          method: "POST",
          credentials: "same-origin",
          cache: "no-store",
          redirect: "error",
          headers: { "Idempotency-Key": key },
          body,
        })
      );
    },
  };
}

export function openDocumentEditor(id: string): void {
  if (!isDocumentId(id)) throw new Error("INVALID_DOCUMENT_ID");
  // A full navigation lets the editor's unload guard cover browser Back.
  window.location.assign(`/app/tools/documents/${id}`);
}

export async function downloadSavedDocument(
  id: string,
  signal?: AbortSignal,
  savedVersion?: DocumentSnapshot
): Promise<void> {
  if (!isDocumentId(id)) throw new Error("INVALID_DOCUMENT_ID");
  const options = {
    signal,
    credentials: "same-origin",
    cache: "no-store",
    redirect: "error",
  } as const;
  const snapshot =
    savedVersion ??
    (await readSnapshot(await fetch(`${DOCUMENTS_API}/${id}`, options)));
  if (snapshot.document_id !== id) throw new Error("INVALID_DOCUMENT_RESPONSE");
  const response = await fetch(
    `${DOCUMENTS_API}/${id}/versions/${snapshot.version_id}/content`,
    options
  );
  if (!response.ok) throw new Error("DOCUMENT_REQUEST_FAILED");
  const bytes = await response.arrayBuffer();
  const hash = Array.from(
    new Uint8Array(await crypto.subtle.digest("SHA-256", bytes)),
    (value) => value.toString(16).padStart(2, "0")
  ).join("");
  if (hash !== snapshot.content_hash) throw new Error("CONTENT_HASH_MISMATCH");
  signal?.throwIfAborted();
  const url = URL.createObjectURL(
    new Blob([bytes], {
      type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    })
  );
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = snapshot.title.replace(/[\\/]/g, "_");
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
