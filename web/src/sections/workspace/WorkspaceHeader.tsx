"use client";

import { Button, Text } from "@opal/components";
import { RootLayout, useSidebarState } from "@opal/layouts";
import { SvgPlus, SvgSettings, SvgSidebar } from "@opal/icons";
import { useTranslations } from "next-intl";
import { usePathname } from "next/navigation";
import useScreenSize from "@/hooks/useScreenSize";

export default function WorkspaceHeader() {
  const t = useTranslations("workspace");
  const { isMobile } = useScreenSize();
  const { setFolded } = useSidebarState();
  const pathname = usePathname();
  if (pathname.startsWith("/app/tools/presentations/")) return null;
  return (
    <RootLayout.Header>
      <div className="workspace-header">
        <div className="flex items-center gap-3">
          {isMobile && (
            <Button
              icon={SvgSidebar}
              prominence="tertiary"
              onClick={() => setFolded(false)}
              aria-label={t("openNavigation")}
            />
          )}
          <Text font="main-ui-action" color="text-04">
            {t("title")}
          </Text>
          <span className="workspace-space-label">
            <Text font="secondary-body" color="text-03">
              {t("personalSpace")}
            </Text>
          </span>
        </div>
        <div className="flex items-center gap-2">
          <Button
            icon={SvgSettings}
            href="/app/settings"
            prominence="tertiary"
            tooltip={t("settings")}
          />
          <Button icon={SvgPlus} href="/app?compose=1" prominence="secondary">
            {t("newChat")}
          </Button>
        </div>
      </div>
    </RootLayout.Header>
  );
}
