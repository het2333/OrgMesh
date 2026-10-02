"use client";

import { Button, Text } from "@opal/components";
import { SvgHistory } from "@opal/icons";
import { useTranslations } from "next-intl";
import DocumentLibrary from "@/sections/workspace/documents/DocumentLibrary";
import PresentationCreator from "@/sections/workspace/presentations/PresentationCreator";
import PresentationJobs from "@/sections/workspace/presentations/PresentationJobs";
import PresentationLibrary from "@/sections/workspace/presentations/PresentationLibrary";

export default function WorkspaceTools() {
  const t = useTranslations("workspace.tools");

  return (
    <div className="workspace-tools" data-testid="Workspace/tools">
      <div className="workspace-page-heading">
        <Text as="h1" font="heading-h2">
          {t("title")}
        </Text>
        <Text as="p" font="main-ui-muted" color="text-03">
          {t("description")}
        </Text>
      </div>

      <Button
        href="/app/tools/history"
        icon={SvgHistory}
        prominence="secondary"
      >
        {t("history.open")}
      </Button>

      <DocumentLibrary />
      <PresentationCreator />
      <PresentationJobs />
      <PresentationLibrary />
    </div>
  );
}
