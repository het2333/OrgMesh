"use client";

import { Button, Text } from "@opal/components";
import {
  SvgArrowUpRight,
  SvgGlobe,
  SvgSettings,
  SvgSparkle,
} from "@opal/icons";
import { useUser } from "@/providers/UserProvider";
import { useSettings } from "@/lib/settings/hooks";
import { useLLMProviders } from "@/lib/languageModels/hooks";
import { hasVisibleLLMModel } from "@/lib/languageModels/utils";
import { useTranslations } from "next-intl";

export default function WorkspaceSettings() {
  const t = useTranslations("workspace");
  const { isAdmin } = useUser();
  const {
    vectorDbEnabled,
    isLoading: settingsLoading,
    error: settingsError,
  } = useSettings();
  const {
    llmProviders,
    isLoading: modelsLoading,
    error: modelsError,
  } = useLLMProviders();
  const modelReady = hasVisibleLLMModel(llmProviders);
  return (
    <div className="workspace-settings-hub">
      <div>
        <Text as="h2" font="heading-h3">
          {t("settingsHub.title")}
        </Text>
        <Text as="p" font="main-ui-muted" color="text-03">
          {t("settingsHub.description")}
        </Text>
      </div>
      {isAdmin ? (
        <Button href="/admin/orgmesh" prominence="secondary" icon={SvgSettings}>
          {t("enterprise.title")}
        </Button>
      ) : null}
      {(
        [
          {
            key: "models",
            icon: SvgSparkle,
            loading: modelsLoading,
            error: modelsError,
            ready: modelReady,
            href: "/admin/language-models",
          },
          {
            key: "knowledge",
            icon: SvgGlobe,
            loading: settingsLoading,
            error: settingsError,
            ready: vectorDbEnabled,
            href: "/admin/indexing/status",
          },
          {
            key: "preferences",
            icon: SvgSettings,
            loading: false,
            error: null,
            ready: true,
            href: "/app/settings/general",
          },
        ] as const
      ).map(({ key, icon: Icon, loading, error, ready, href }) => (
        <div key={key} className="workspace-settings-card">
          <div className="flex items-start gap-3">
            <div className="workspace-icon-tile">
              <Icon size={22} />
            </div>
            <div className="flex flex-col gap-2">
              <Text font="main-ui-action">{t(`settingsHub.${key}.title`)}</Text>
              <Text font="main-ui-muted" color="text-03">
                {t(`settingsHub.${key}.description`)}
              </Text>
              <Text
                font="secondary-action"
                color={error ? "status-error-05" : "text-03"}
              >
                {t(
                  loading
                    ? "loading"
                    : error
                      ? "loadError"
                      : ready
                        ? "ready"
                        : "needsSetup"
                )}
              </Text>
            </div>
          </div>
          <Button href={href} prominence="secondary" icon={SvgArrowUpRight}>
            {t("manage")}
          </Button>
        </div>
      ))}
    </div>
  );
}
