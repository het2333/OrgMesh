"use client";

import { useState } from "react";
import useSWR from "swr";
import { useTranslations } from "next-intl";
import { Button, IconLoader, Text } from "@opal/components";
import { IllustrationContent, useSidebarState } from "@opal/layouts";
import { SvgArrowLeft, SvgRefreshCw, SvgSidebar } from "@opal/icons";
import useScreenSize from "@/hooks/useScreenSize";
import { errorHandlingFetcher, skipRetryOnAuthError } from "@/lib/fetcher";
import { type WorkspacePresentation } from "@/sections/workspace/presentations/types";

interface PresentationEditorProps {
  id: string;
}

export default function PresentationEditor({ id }: PresentationEditorProps) {
  const t = useTranslations("workspace.tools.presenton");
  const tw = useTranslations("workspace");
  const { isMobile } = useScreenSize();
  const { setFolded } = useSidebarState();
  const [frameLoaded, setFrameLoaded] = useState(false);
  const {
    data: presentation,
    error,
    isLoading,
    mutate,
  } = useSWR<WorkspacePresentation>(
    `/presenton/api/v1/ppt/presentation/${encodeURIComponent(id)}`,
    errorHandlingFetcher,
    { onErrorRetry: skipRetryOnAuthError }
  );
  return (
    <div
      className="workspace-presentation-editor"
      data-testid="Presentation/editor"
    >
      <div className="workspace-presentation-editor-header">
        {isMobile && (
          <Button
            icon={SvgSidebar}
            prominence="tertiary"
            size="sm"
            aria-label={tw("openNavigation")}
            onClick={() => setFolded(false)}
          />
        )}
        <Button
          icon={SvgArrowLeft}
          href="/app/tools"
          prominence="tertiary"
          size="sm"
        >
          {t("back")}
        </Button>
        <div className="workspace-presentation-editor-title">
          <Text font="main-ui-action" maxLines={1}>
            {t("title")}
          </Text>
        </div>
        <Text font="secondary-body" color="text-03">
          {t("editorHint")}
        </Text>
      </div>
      {isLoading ? (
        <div className="workspace-presentation-editor-message" role="status">
          <IconLoader size={24} />
          <Text font="main-ui-muted">{t("editorLoading")}</Text>
        </div>
      ) : error || !presentation ? (
        <div className="workspace-presentation-editor-message">
          <IllustrationContent
            title={t("editorError")}
            description={t("editorErrorHint")}
          />
          <Button
            icon={SvgRefreshCw}
            prominence="secondary"
            onClick={() => void mutate()}
          >
            {t("retry")}
          </Button>
        </div>
      ) : (
        <div className="workspace-presentation-editor-frame">
          {!frameLoaded && (
            <div
              className="workspace-presentation-editor-message workspace-presentation-editor-overlay"
              role="status"
            >
              <IconLoader size={24} />
              <Text font="main-ui-muted">{t("editorLoading")}</Text>
            </div>
          )}
          <iframe
            src={`/presenton/presentation?id=${encodeURIComponent(id)}`}
            title={t("editorTitle", {
              title: presentation.title || t("untitled"),
            })}
            allow="fullscreen"
            allowFullScreen
            onLoad={() => setFrameLoaded(true)}
          />
        </div>
      )}
    </div>
  );
}
