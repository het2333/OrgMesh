"use client";

import { useTranslations } from "next-intl";
import { getDisplayNameForCredentialKey } from "@/lib/connectors/credentials";

export function useCredentialDisplayName() {
  const t = useTranslations("admin.connectorsList");
  return function credentialDisplayName(key: string): string {
    if (key === "feishu_app_id") return t("feishu.appId.label");
    if (key === "feishu_app_secret") return t("feishu.appSecret.label");
    return getDisplayNameForCredentialKey(key);
  };
}
