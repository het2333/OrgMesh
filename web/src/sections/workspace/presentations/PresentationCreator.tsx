"use client";

import { useRef, useState, type ChangeEvent, type FormEvent } from "react";
import useSWR, { useSWRConfig } from "swr";
import { useTranslations } from "next-intl";
import {
  Button,
  IconLoader,
  InputTextArea,
  InputTypeIn,
  Text,
} from "@opal/components";
import {
  SvgFileText,
  SvgSlidesFile,
  SvgSparkle,
  SvgUploadCloud,
  SvgX,
} from "@opal/icons";
import { errorHandlingFetcher, skipRetryOnAuthError } from "@/lib/fetcher";
import {
  PRESENTON_API,
  PRESENTON_JOBS_KEY,
  PRESENTON_LIBRARY_KEY,
  type PresentationAttachment,
  type PresentationGenerationResponse,
  type PresentationJob,
  type PresentationStatus,
} from "@/sections/workspace/presentations/types";

const MAX_UPLOAD_BYTES = 20 * 1024 * 1024;
const MAX_UPLOAD_FILES = 5;

export default function PresentationCreator() {
  const t = useTranslations("workspace.tools.presenton");
  const { mutate } = useSWRConfig();
  const {
    data: status,
    error: statusError,
    isLoading,
    mutate: refreshStatus,
  } = useSWR<PresentationStatus>(
    `${PRESENTON_API}/status`,
    errorHandlingFetcher,
    { onErrorRetry: skipRetryOnAuthError, refreshInterval: 30000 }
  );
  const { data: jobs } = useSWR<PresentationJob[]>(
    PRESENTON_JOBS_KEY,
    errorHandlingFetcher,
    { onErrorRetry: skipRetryOnAuthError }
  );
  const [content, setContent] = useState("");
  const [slideCount, setSlideCount] = useState("6");
  const [attachments, setAttachments] = useState<PresentationAttachment[]>([]);
  const [uploading, setUploading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitted, setSubmitted] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const submitInFlight = useRef(false);
  const ready = status?.available && Boolean(status.model_name);
  const hasPendingJob = jobs?.some((job) => job.status === "pending") ?? false;
  const nSlides = Number(slideCount);
  const validSlideCount =
    Number.isInteger(nSlides) && nSlides >= 3 && nSlides <= 20;

  async function uploadFiles(event: ChangeEvent<HTMLInputElement>) {
    const files = Array.from(event.target.files ?? []);
    event.target.value = "";
    if (!files.length) return;
    setError(null);
    setSubmitted(false);
    if (
      files.length + attachments.length > MAX_UPLOAD_FILES ||
      files.reduce((total, file) => total + file.size, 0) +
        attachments.reduce((total, file) => total + file.size, 0) >
        MAX_UPLOAD_BYTES
    ) {
      setError(t("uploadLimit"));
      return;
    }
    setUploading(true);
    try {
      const formData = new FormData();
      for (const file of files) formData.append("files", file);
      const response = await fetch("/presenton/api/v1/ppt/files/upload", {
        method: "POST",
        body: formData,
      });
      if (!response.ok) throw new Error("Presentation upload failed");
      const paths: string[] = await response.json();
      if (
        !Array.isArray(paths) ||
        paths.length !== files.length ||
        !paths.every((path) => typeof path === "string" && path.length > 0)
      ) {
        throw new Error("Invalid presentation upload response");
      }
      setAttachments((current) => [
        ...current,
        ...paths.map((path, index) => ({
          name: files[index]?.name ?? t("document"),
          path,
          size: files[index]?.size ?? 0,
        })),
      ]);
    } catch {
      setError(t("uploadError"));
    } finally {
      setUploading(false);
    }
  }

  async function generate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (
      !ready ||
      !content.trim() ||
      !validSlideCount ||
      uploading ||
      hasPendingJob ||
      submitInFlight.current
    )
      return;
    submitInFlight.current = true;
    setSubmitting(true);
    setError(null);
    setSubmitted(false);
    try {
      const response = await fetch(`${PRESENTON_API}/generate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          content: content.trim(),
          n_slides: nSlides,
          language: "Chinese",
          template: "general",
          files: attachments.map((attachment) => attachment.path),
        }),
      });
      if (!response.ok) throw new Error("Presentation generation failed");
      const result: PresentationGenerationResponse = await response.json();
      if (!result.task_id) throw new Error("Missing presentation task id");
      setSubmitted(true);
      setAttachments([]);
      await Promise.allSettled([
        mutate(PRESENTON_JOBS_KEY),
        mutate(PRESENTON_LIBRARY_KEY),
      ]);
    } catch {
      setError(t("generateError"));
    } finally {
      submitInFlight.current = false;
      setSubmitting(false);
    }
  }

  return (
    <section
      className="workspace-presentation-create"
      aria-labelledby="presentation-create-title"
    >
      <div className="workspace-presentation-intro">
        <div className="workspace-icon-tile">
          <SvgSlidesFile size={24} />
        </div>
        <div className="workspace-presentation-title">
          <Text as="h2" font="heading-h3" id="presentation-create-title">
            {t("title")}
          </Text>
          <Text as="p" font="main-ui-muted" color="text-03">
            {t("description")}
          </Text>
        </div>
      </div>
      {isLoading ? (
        <div className="workspace-presentation-notice" role="status">
          <IconLoader size={16} />
          <Text font="secondary-body" color="text-03">
            {t("connecting")}
          </Text>
        </div>
      ) : statusError || !status?.available ? (
        <div className="workspace-presentation-notice" role="status">
          <Text font="main-ui-muted" color="status-error-05">
            {t("unavailable")}
          </Text>
          <Button
            prominence="secondary"
            size="sm"
            onClick={() => void refreshStatus()}
          >
            {t("retry")}
          </Button>
        </div>
      ) : status.model_name ? (
        <div className="workspace-presentation-notice">
          <SvgSparkle size={16} />
          <Text font="secondary-body" color="text-03">
            {t("model", {
              model: status.model_name,
              provider: status.provider || t("defaultProvider"),
            })}
          </Text>
          <Text font="secondary-body" color="text-03">
            {t("format")}
          </Text>
        </div>
      ) : (
        <Text as="p" font="main-ui-muted" color="status-error-05">
          {t("modelMissing")}
        </Text>
      )}
      <form className="workspace-presentation-form" onSubmit={generate}>
        <label htmlFor="presentation-content">
          <Text font="main-ui-action">{t("contentLabel")}</Text>
        </label>
        <InputTextArea
          id="presentation-content"
          value={content}
          onChange={(event) => {
            setContent(event.target.value);
            setSubmitted(false);
          }}
          placeholder={t("contentPlaceholder")}
          rows={5}
          maxLength={20000}
          required
          variant={submitting ? "disabled" : "primary"}
        />
        <div className="workspace-presentation-options">
          <div className="workspace-presentation-slide-count">
            <label htmlFor="presentation-slide-count">
              <Text font="secondary-action">{t("slidesLabel")}</Text>
            </label>
            <InputTypeIn
              id="presentation-slide-count"
              type="number"
              min={3}
              max={20}
              step={1}
              required
              value={slideCount}
              onChange={(event) => setSlideCount(event.target.value)}
              variant={submitting ? "disabled" : "primary"}
            />
          </div>
          <div className="workspace-presentation-upload">
            <div hidden>
              <InputTypeIn
                ref={fileInput}
                type="file"
                multiple
                accept=".pdf,.docx,.pptx,.txt"
                onChange={(event) => void uploadFiles(event)}
                aria-label={t("attach")}
              />
            </div>
            <Button
              icon={SvgUploadCloud}
              prominence="secondary"
              disabled={
                !ready ||
                uploading ||
                submitting ||
                attachments.length >= MAX_UPLOAD_FILES
              }
              onClick={() => fileInput.current?.click()}
            >
              {t(uploading ? "uploading" : "attach")}
            </Button>
            <Text font="secondary-body" color="text-03">
              {t("uploadHint")}
            </Text>
          </div>
        </div>
        {attachments.length > 0 && (
          <div className="workspace-presentation-attachments">
            {attachments.map((attachment) => (
              <div
                className="workspace-presentation-attachment"
                key={attachment.path}
              >
                <SvgFileText size={16} />
                <Text font="secondary-body" maxLines={1}>
                  {attachment.name}
                </Text>
                <Button
                  icon={SvgX}
                  prominence="tertiary"
                  size="sm"
                  disabled={submitting}
                  aria-label={t("removeFile", { name: attachment.name })}
                  onClick={() =>
                    setAttachments((current) =>
                      current.filter((file) => file.path !== attachment.path)
                    )
                  }
                />
              </div>
            ))}
          </div>
        )}
        {error && (
          <Text
            as="p"
            font="main-ui-muted"
            color="status-error-05"
            role="alert"
          >
            {error}
          </Text>
        )}
        {submitted && (
          <Text
            as="p"
            font="main-ui-muted"
            color="status-success-05"
            role="status"
          >
            {t("submitted")}
          </Text>
        )}
        {hasPendingJob && (
          <Text as="p" font="secondary-body" color="text-03">
            {t("oneJobAtATime")}
          </Text>
        )}
        <div className="workspace-presentation-submit">
          <Text font="secondary-body" color="text-03">
            {t("textOnly")}
          </Text>
          <Button
            type="submit"
            icon={SvgSparkle}
            disabled={
              !ready ||
              !content.trim() ||
              !validSlideCount ||
              uploading ||
              submitting ||
              hasPendingJob
            }
          >
            {t(submitting ? "submitting" : "generate")}
          </Button>
        </div>
      </form>
    </section>
  );
}
