"use client";

import { useState } from "react";
import useSWR from "swr";
import { useFormatter, useTranslations } from "next-intl";
import {
  BasicModalFooter,
  Button,
  IconLoader,
  Modal,
  Text,
} from "@opal/components";
import { IllustrationContent } from "@opal/layouts";
import { SvgRefreshCw, SvgSlidesFile, SvgTrash } from "@opal/icons";
import { errorHandlingFetcher, skipRetryOnAuthError } from "@/lib/fetcher";
import {
  PRESENTON_JOBS_KEY,
  PRESENTON_LIBRARY_KEY,
  PRESENTON_TIME_ZONE,
  isPresentationId,
  presentationEditorHref,
  type PresentationJob,
  type WorkspacePresentation,
} from "@/sections/workspace/presentations/types";

export default function PresentationLibrary() {
  const t = useTranslations("workspace.tools.presenton");
  const formatter = useFormatter();
  const {
    data: presentations,
    error,
    isLoading,
    mutate,
  } = useSWR<WorkspacePresentation[]>(
    PRESENTON_LIBRARY_KEY,
    errorHandlingFetcher,
    { onErrorRetry: skipRetryOnAuthError, refreshInterval: 10000 }
  );
  const { data: jobs } = useSWR<PresentationJob[]>(
    PRESENTON_JOBS_KEY,
    errorHandlingFetcher,
    { onErrorRetry: skipRetryOnAuthError }
  );
  const [deleting, setDeleting] = useState<WorkspacePresentation | null>(null);
  const [deletePending, setDeletePending] = useState(false);
  const [deleteError, setDeleteError] = useState(false);
  const pendingIds = new Set(
    jobs
      ?.filter((job) => job.status === "pending")
      .map((job) => job.data?.presentation_id)
  );

  async function deletePresentation() {
    if (!deleting || deletePending) return;
    setDeletePending(true);
    setDeleteError(false);
    try {
      const response = await fetch(
        `/presenton/api/v1/ppt/presentation/${encodeURIComponent(deleting.id)}`,
        { method: "DELETE" }
      );
      if (!response.ok) throw new Error("Presentation delete failed");
      setDeleting(null);
      await mutate();
    } catch {
      setDeleteError(true);
    } finally {
      setDeletePending(false);
    }
  }

  return (
    <section
      className="workspace-presentation-library"
      aria-labelledby="presentation-library-title"
    >
      <div className="workspace-presentation-library-heading">
        <Text as="h2" font="heading-h3" id="presentation-library-title">
          {t("libraryTitle")}
        </Text>
        <Button
          icon={SvgRefreshCw}
          prominence="tertiary"
          size="sm"
          onClick={() => void mutate()}
          aria-label={t("refresh")}
          tooltip={t("refresh")}
        />
      </div>
      {isLoading ? (
        <div className="workspace-loading" role="status">
          <IconLoader size={20} />
          <Text font="main-ui-muted">{t("libraryLoading")}</Text>
        </div>
      ) : error ? (
        <div className="workspace-presentation-empty">
          <IllustrationContent
            title={t("libraryError")}
            description={t("retryHint")}
          />
          <Button prominence="secondary" onClick={() => void mutate()}>
            {t("retry")}
          </Button>
        </div>
      ) : !presentations?.length ? (
        <div className="workspace-presentation-empty">
          <IllustrationContent
            title={t("emptyTitle")}
            description={t("emptyDescription")}
          />
        </div>
      ) : (
        <div className="workspace-presentation-grid">
          {presentations
            .filter((presentation) => isPresentationId(presentation.id))
            .map((presentation) => {
              const pending = pendingIds.has(presentation.id);
              return (
                <article
                  className="workspace-presentation-card"
                  key={presentation.id}
                >
                  <div className="workspace-presentation-card-top">
                    <div className="workspace-icon-tile">
                      <SvgSlidesFile size={23} />
                    </div>
                    <Button
                      icon={SvgTrash}
                      prominence="tertiary"
                      size="sm"
                      disabled={pending}
                      tooltip={t("delete")}
                      aria-label={t("deleteNamed", {
                        title: presentation.title || t("untitled"),
                      })}
                      onClick={() => {
                        setDeleting(presentation);
                        setDeleteError(false);
                      }}
                    />
                  </div>
                  <Text as="h3" font="main-content-emphasis" maxLines={2}>
                    {presentation.title || t("untitled")}
                  </Text>
                  <div className="workspace-presentation-card-meta">
                    <Text font="secondary-body" color="text-03">
                      {t("slideCount", { count: presentation.n_slides })}
                    </Text>
                    <Text font="secondary-body" color="text-03">
                      {formatter.dateTime(
                        new Date(
                          presentation.updated_at ?? presentation.created_at
                        ),
                        {
                          timeZone: PRESENTON_TIME_ZONE,
                          year: "numeric",
                          month: "short",
                          day: "numeric",
                        }
                      )}
                    </Text>
                  </div>
                  <Button
                    href={presentationEditorHref(presentation.id)}
                    prominence="secondary"
                    disabled={pending}
                  >
                    {t(pending ? "jobStatus.pending" : "openEditor")}
                  </Button>
                </article>
              );
            })}
        </div>
      )}
      <Modal
        open={Boolean(deleting)}
        onOpenChange={(open) => {
          if (!open && !deletePending) setDeleting(null);
        }}
      >
        <Modal.Content width="sm">
          <Modal.Header
            icon={SvgTrash}
            title={t("deleteTitle")}
            description={t("deleteDescription", {
              title: deleting?.title || t("untitled"),
            })}
            onClose={() => {
              if (!deletePending) setDeleting(null);
            }}
          />
          {deleteError && (
            <Modal.Body>
              <Text font="main-ui-muted" color="status-error-05" role="alert">
                {t("deleteError")}
              </Text>
            </Modal.Body>
          )}
          <Modal.Footer>
            <BasicModalFooter
              cancel={
                <Button
                  prominence="secondary"
                  disabled={deletePending}
                  onClick={() => setDeleting(null)}
                >
                  {t("cancel")}
                </Button>
              }
              submit={
                <Button
                  variant="danger"
                  disabled={deletePending}
                  onClick={() => void deletePresentation()}
                >
                  {t(deletePending ? "deleting" : "delete")}
                </Button>
              }
            />
          </Modal.Footer>
        </Modal.Content>
      </Modal>
    </section>
  );
}
