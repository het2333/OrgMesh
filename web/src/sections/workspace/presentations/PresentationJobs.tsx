"use client";

import useSWR from "swr";
import { useFormatter, useTranslations } from "next-intl";
import { Button, IconLoader, ProgressBar, Text } from "@opal/components";
import { SvgCheckCircle, SvgRefreshCw } from "@opal/icons";
import { errorHandlingFetcher, skipRetryOnAuthError } from "@/lib/fetcher";
import {
  PRESENTON_JOBS_KEY,
  PRESENTON_TIME_ZONE,
  isPresentationId,
  presentationEditorHref,
  type PresentationJob,
} from "@/sections/workspace/presentations/types";

export default function PresentationJobs() {
  const t = useTranslations("workspace.tools.presenton");
  const formatter = useFormatter();
  const {
    data: jobs,
    error,
    isLoading,
    mutate,
  } = useSWR<PresentationJob[]>(PRESENTON_JOBS_KEY, errorHandlingFetcher, {
    onErrorRetry: skipRetryOnAuthError,
    refreshInterval: (data) =>
      data?.some((job) => job.status === "pending") ? 3000 : 30000,
  });

  if (isLoading) {
    return (
      <div className="workspace-loading" role="status">
        <IconLoader size={20} />
        <Text font="main-ui-muted">{t("jobsLoading")}</Text>
      </div>
    );
  }
  if (error) {
    return (
      <div className="workspace-presentation-notice" role="alert">
        <Text font="main-ui-muted" color="status-error-05">
          {t("jobsError")}
        </Text>
        <Button
          prominence="secondary"
          size="sm"
          icon={SvgRefreshCw}
          onClick={() => void mutate()}
        >
          {t("retry")}
        </Button>
      </div>
    );
  }
  if (!jobs?.length) return null;

  return (
    <section
      className="workspace-presentation-jobs"
      aria-labelledby="presentation-jobs-title"
    >
      <Text as="h2" font="heading-h3" id="presentation-jobs-title">
        {t("jobsTitle")}
      </Text>
      <div className="workspace-presentation-job-list">
        {jobs.slice(0, 5).map((job) => {
          const created = job.data?.created_slides ?? 0;
          const remaining = job.data?.remaining_slides ?? 0;
          const presentationId = job.data?.presentation_id;
          const editorHref =
            presentationId && isPresentationId(presentationId)
              ? presentationEditorHref(presentationId)
              : null;
          return (
            <article className="workspace-presentation-job" key={job.id}>
              <div className="workspace-presentation-job-main">
                {job.status === "pending" ? (
                  <IconLoader size={18} />
                ) : job.status === "completed" ? (
                  <SvgCheckCircle size={18} />
                ) : (
                  <SvgRefreshCw size={18} />
                )}
                <div
                  className="workspace-presentation-job-copy"
                  aria-live={job.status === "pending" ? "polite" : "off"}
                >
                  <Text
                    font="main-ui-action"
                    color={
                      job.status === "error" ? "status-error-05" : "text-04"
                    }
                  >
                    {t(`jobStatus.${job.status}`)}
                  </Text>
                  <Text font="secondary-body" color="text-03">
                    {job.status === "pending"
                      ? created > 0
                        ? t("jobProgress", {
                            created,
                            total: created + remaining,
                          })
                        : t("jobPreparing")
                      : job.status === "error"
                        ? t("jobFailed")
                        : t("jobCompleted")}
                  </Text>
                  {job.status === "pending" && created + remaining > 0 && (
                    <ProgressBar
                      value={created}
                      max={created + remaining}
                      color="purple"
                    />
                  )}
                </div>
              </div>
              <div className="workspace-presentation-job-actions">
                <Text font="secondary-body" color="text-03">
                  {formatter.dateTime(new Date(job.created_at), {
                    timeZone: PRESENTON_TIME_ZONE,
                    month: "short",
                    day: "numeric",
                    hour: "numeric",
                    minute: "numeric",
                  })}
                </Text>
                {job.status === "completed" && editorHref && (
                  <Button href={editorHref} prominence="secondary" size="sm">
                    {t("openEditor")}
                  </Button>
                )}
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}
