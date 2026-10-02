"use client";

import { useEffect, useRef, useState, type ChangeEvent } from "react";
import useSWR from "swr";
import { useTranslations } from "next-intl";
import { Button, IconLoader, InputTypeIn, Text } from "@opal/components";
import { SvgDownload, SvgFileText, SvgPlus, SvgRefreshCw } from "@opal/icons";
import { useUser } from "@/providers/UserProvider";
import { errorHandlingFetcher, skipRetryOnAuthError } from "@/lib/fetcher";
import {
  DOCUMENTS_API,
  MAX_DOCUMENT_BYTES,
  createDocumentRequest,
  downloadSavedDocument,
  isDocumentSnapshot,
  openDocumentEditor,
} from "@/sections/workspace/documents/api";

function fetchOwned<T>([url]: readonly [string, string]): Promise<T> {
  return errorHandlingFetcher<T>(url);
}

function DocumentLibraryContent({ owner }: { owner: string }) {
  const t = useTranslations("workspace.tools.word");
  const {
    data,
    error: listError,
    isLoading,
    mutate,
  } = useSWR<unknown>([DOCUMENTS_API, owner], fetchOwned, {
    onErrorRetry: skipRetryOnAuthError,
  });
  const documents = Array.isArray(data) ? data.filter(isDocumentSnapshot) : [];
  const [title, setTitle] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<
    "fileError" | "createError" | "downloadError" | null
  >(null);
  const inFlight = useRef(false);
  const active = useRef(true);
  const downloadController = useRef<AbortController | null>(null);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
      downloadController.current?.abort();
    };
  }, []);
  const request = useRef<ReturnType<typeof createDocumentRequest> | null>(null);

  function selectFile(event: ChangeEvent<HTMLInputElement>) {
    const selected = event.target.files?.[0] ?? null;
    event.target.value = "";
    request.current = null;
    setError(null);
    if (
      selected &&
      (!selected.name.toLowerCase().endsWith(".docx") ||
        selected.size > MAX_DOCUMENT_BYTES)
    ) {
      setError("fileError");
      setFile(null);
      return;
    }
    setFile(selected);
    if (selected) setTitle(selected.name);
  }

  async function create() {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    setError(null);
    request.current ??= createDocumentRequest(
      title || file?.name || t("untitled"),
      file
    );
    try {
      const saved = await request.current.submit();
      if (!active.current) return;
      await mutate();
      if (!active.current) return;
      openDocumentEditor(saved.document_id);
    } catch {
      if (active.current) setError("createError");
    } finally {
      inFlight.current = false;
      if (active.current) setBusy(false);
    }
  }

  async function download(id: string) {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    setError(null);
    try {
      downloadController.current = new AbortController();
      await downloadSavedDocument(id, downloadController.current.signal);
    } catch {
      if (active.current) setError("downloadError");
    } finally {
      inFlight.current = false;
      if (active.current) setBusy(false);
    }
  }

  return (
    <section
      className="workspace-word-library"
      aria-labelledby="word-library-title"
      data-testid="Word/library"
    >
      <div className="flex items-center gap-2">
        <SvgFileText size={24} />
        <Text as="h2" font="heading-h3" id="word-library-title">
          {t("title")}
        </Text>
        <Button
          icon={SvgRefreshCw}
          prominence="tertiary"
          onClick={() => void mutate()}
          aria-label={t("refresh")}
        />
      </div>
      <Text as="p" font="main-ui-muted" color="text-03">
        {t("description")}
      </Text>
      <div className="workspace-word-create">
        <InputTypeIn
          data-testid="Word/name"
          aria-label={t("name")}
          placeholder={t("name")}
          value={title}
          maxLength={200}
          variant={busy ? "disabled" : "primary"}
          onChange={(event) => {
            setTitle(event.target.value);
            request.current = null;
          }}
        />
        <InputTypeIn
          type="file"
          accept=".docx"
          data-testid="Word/file"
          aria-label={t("import")}
          variant={busy ? "disabled" : "primary"}
          onChange={selectFile}
        />
        {file && (
          <>
            <Text font="secondary-body">{file.name}</Text>
            <Button
              prominence="tertiary"
              disabled={busy}
              onClick={() => {
                setFile(null);
                setTitle("");
                request.current = null;
              }}
            >
              {t("clearFile")}
            </Button>
          </>
        )}
        <Button
          data-testid="Word/create"
          icon={SvgPlus}
          disabled={busy}
          onClick={() => void create()}
        >
          {file ? t("importOpen") : t("create")}
        </Button>
      </div>
      {error && (
        <Text as="p" font="main-ui-muted" color="text-03" role="alert">
          {t(error)}
        </Text>
      )}
      {isLoading ? (
        <IconLoader size={20} />
      ) : listError ? (
        <Text as="p" font="main-ui-muted" role="alert">
          {t("listError")}
        </Text>
      ) : documents.length === 0 ? (
        <Text as="p" font="main-ui-muted" color="text-03">
          {t("empty")}
        </Text>
      ) : (
        <ul className="workspace-word-list">
          {documents.map((document) => (
            <li key={document.document_id} className="workspace-word-row">
              <Text font="main-ui-action">{document.title}</Text>
              <div className="flex gap-2">
                <Button
                  prominence="secondary"
                  disabled={busy}
                  onClick={() => openDocumentEditor(document.document_id)}
                >
                  {t("open")}
                </Button>
                <Button
                  icon={SvgDownload}
                  prominence="tertiary"
                  disabled={busy}
                  onClick={() => void download(document.document_id)}
                >
                  {t("download")}
                </Button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export default function DocumentLibrary() {
  const { user, isUserLoading } = useUser();
  const owner = isUserLoading ? undefined : user?.id;
  const { data: status } = useSWR<{ enabled: boolean }>(
    owner ? [`${DOCUMENTS_API}/status`, owner] : null,
    fetchOwned,
    { onErrorRetry: skipRetryOnAuthError }
  );
  if (!owner || !status?.enabled) return null;
  return <DocumentLibraryContent key={owner} owner={owner} />;
}
