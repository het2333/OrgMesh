"use client";

import { useEffect, useRef, useState } from "react";
import useSWR from "swr";
import { useLocale, useTranslations } from "next-intl";
import { Button, IconLoader, Text } from "@opal/components";
import { SvgArrowLeft, SvgDownload, SvgUploadCloud } from "@opal/icons";
import { useUser } from "@/providers/UserProvider";
import { errorHandlingFetcher, skipRetryOnAuthError } from "@/lib/fetcher";
import {
  DOCUMENTS_API,
  downloadSavedDocument,
  isDocumentSnapshot,
  type DocumentSnapshot,
} from "@/sections/workspace/documents/api";

interface BrowserEditor {
  save(): Promise<boolean>;
  hasUnsavedChanges(): boolean;
  getSnapshot(): DocumentSnapshot | null;
}
function frameEditor(frame: HTMLIFrameElement | null): BrowserEditor | null {
  const window = frame?.contentWindow;
  if (!window || !("orgmeshDocs" in window)) return null;
  const api = window.orgmeshDocs;
  if (
    typeof api !== "object" ||
    api === null ||
    !("save" in api) ||
    typeof api.save !== "function" ||
    !("hasUnsavedChanges" in api) ||
    typeof api.hasUnsavedChanges !== "function" ||
    !("getSnapshot" in api) ||
    typeof api.getSnapshot !== "function"
  )
    return null;
  // SAFETY: The same-origin browser entry exposes these three checked methods.
  return api as BrowserEditor;
}
function fetchOwned<T>([url]: readonly [string, string]): Promise<T> {
  return errorHandlingFetcher<T>(url);
}

function EditorContent({ id, owner }: { id: string; owner: string }) {
  const t = useTranslations("workspace.tools.word");
  const locale = useLocale();
  const frame = useRef<HTMLIFrameElement>(null);
  const inFlight = useRef(false);
  const active = useRef(true);
  const controller = useRef<AbortController | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<
    "editorError" | "saveError" | "downloadError" | null
  >(null);
  const {
    data,
    error: loadError,
    isLoading,
  } = useSWR<unknown>([`${DOCUMENTS_API}/${id}`, owner], fetchOwned, {
    onErrorRetry: skipRetryOnAuthError,
  });
  const document =
    isDocumentSnapshot(data) && data.document_id === id ? data : null;

  useEffect(() => {
    active.current = true;
    function hasChanges() {
      return (
        inFlight.current || !!frameEditor(frame.current)?.hasUnsavedChanges()
      );
    }
    function beforeUnload(event: BeforeUnloadEvent) {
      if (!hasChanges()) return;
      event.preventDefault();
      event.returnValue = "";
    }
    function leave(event: MouseEvent) {
      const anchor =
        event.target instanceof Element
          ? event.target.closest("a[href]")
          : null;
      if (
        !(anchor instanceof HTMLAnchorElement) ||
        anchor.target === "_blank" ||
        anchor.hasAttribute("download")
      )
        return;
      if (hasChanges() && !window.confirm(t("leaveConfirm"))) {
        event.preventDefault();
        event.stopPropagation();
      }
    }
    window.addEventListener("beforeunload", beforeUnload);
    window.document.addEventListener("click", leave, true);
    return () => {
      active.current = false;
      controller.current?.abort();
      window.removeEventListener("beforeunload", beforeUnload);
      window.document.removeEventListener("click", leave, true);
    };
  }, [t]);

  async function save(download: boolean) {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    setError(null);
    try {
      if (!(await frameEditor(frame.current)?.save())) {
        if (active.current) setError("saveError");
        return;
      }
      if (!active.current) return;
      if (download) {
        controller.current = new AbortController();
        const snapshot = frameEditor(frame.current)?.getSnapshot();
        if (!isDocumentSnapshot(snapshot) || snapshot.document_id !== id)
          throw new Error("INVALID_DOCUMENT_RESPONSE");
        await downloadSavedDocument(id, controller.current.signal, snapshot);
      }
    } catch {
      if (active.current) setError(download ? "downloadError" : "saveError");
    } finally {
      inFlight.current = false;
      if (active.current) setBusy(false);
    }
  }

  return (
    <div className="workspace-presentation-editor" data-testid="Word/editor">
      <div className="workspace-presentation-editor-header">
        <Button href="/app/tools" icon={SvgArrowLeft} prominence="tertiary">
          {t("back")}
        </Button>
        <div className="workspace-presentation-editor-title">
          <Text font="main-ui-action">{document?.title ?? t("title")}</Text>
        </div>
        <Button
          data-testid="Word/save"
          icon={SvgUploadCloud}
          disabled={!loaded || busy || !document}
          onClick={() => void save(false)}
        >
          {t("save")}
        </Button>
        <Button
          data-testid="Word/download"
          icon={SvgDownload}
          prominence="secondary"
          disabled={!loaded || busy || !document}
          onClick={() => void save(true)}
        >
          {t("download")}
        </Button>
      </div>
      <Text as="p" font="secondary-body" color="text-03">
        {t("editorHint")}
      </Text>
      {error && (
        <Text as="p" font="main-ui-muted" role="alert">
          {t(error)}
        </Text>
      )}
      {isLoading ? (
        <IconLoader size={24} />
      ) : loadError || !document ? (
        <Text as="p" font="main-ui-muted" role="alert">
          {t("editorError")}
        </Text>
      ) : (
        <div className="workspace-presentation-editor-frame">
          <iframe
            data-testid="Word/frame"
            ref={frame}
            src={`/office/docs/index.html?document_id=${encodeURIComponent(id)}&lang=${encodeURIComponent(locale)}`}
            title={t("editorTitle", { title: document.title })}
            onLoad={() => {
              const available = frameEditor(frame.current) !== null;
              setLoaded(available);
              if (!available) setError("editorError");
            }}
          />
        </div>
      )}
    </div>
  );
}

export default function DocumentEditor({ id }: { id: string }) {
  const t = useTranslations("workspace.tools.word");
  const { user, isUserLoading } = useUser();
  const owner = isUserLoading ? undefined : user?.id;
  const { data: status, isLoading } = useSWR<{ enabled: boolean }>(
    owner ? [`${DOCUMENTS_API}/status`, owner] : null,
    fetchOwned,
    { onErrorRetry: skipRetryOnAuthError }
  );
  if (isLoading || isUserLoading) return <IconLoader size={24} />;
  if (!owner || !status?.enabled)
    return <Text font="main-ui-muted">{t("unavailable")}</Text>;
  return <EditorContent key={`${owner}:${id}`} id={id} owner={owner} />;
}
