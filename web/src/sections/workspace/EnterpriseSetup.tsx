"use client";

import { useState } from "react";
import useSWR from "swr";
import { useFormatter, useTranslations } from "next-intl";
import { Button, InputTextArea, Text } from "@opal/components";
import { SvgSettings } from "@opal/icons";
import { SettingsLayouts } from "@opal/layouts";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import { errorHandlingFetcher } from "@/lib/fetcher";

interface EnterpriseStatus {
  search_enabled: boolean;
  local_demo_access: boolean;
  sso_providers: number;
  directory_users: number;
  directory_last_sync: string | null;
  directory_config: { enabled: boolean; credential_id: number | null };
}
interface CredentialSummary {
  id: number;
  source: string;
  name?: string;
}
interface ChineseSettings {
  enabled: boolean;
  glossary: { term: string; expansions: string[] }[];
  max_expansions: number;
}
interface DirectoryConfiguration {
  enabled: boolean;
  credential_id: number;
}

async function saveJson(
  url: string,
  method: string,
  payload?: ChineseSettings | DirectoryConfiguration
) {
  const response = await fetch(url, {
    method,
    headers: { "Content-Type": "application/json" },
    body: payload === undefined ? undefined : JSON.stringify(payload),
  });
  if (!response.ok) throw new Error(String(response.status));
}

export default function EnterpriseSetup() {
  const t = useTranslations("workspace.enterprise");
  const format = useFormatter();
  const {
    data: status,
    error: statusError,
    mutate: refreshStatus,
  } = useSWR<EnterpriseStatus>(
    "/api/manage/admin/orgmesh/status",
    errorHandlingFetcher
  );
  const { data: credentials } = useSWR<CredentialSummary[]>(
    "/api/manage/credential",
    errorHandlingFetcher
  );
  const {
    data: chinese,
    error: chineseError,
    mutate: refreshChinese,
  } = useSWR<ChineseSettings>(
    "/api/manage/admin/chinese-retrieval",
    errorHandlingFetcher
  );
  const [credentialId, setCredentialId] = useState<string | null>(null);
  const [glossaryDraft, setGlossaryDraft] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [feedback, setFeedback] = useState("");
  const currentCredential =
    credentialId ?? String(status?.directory_config.credential_id ?? "");
  const glossaryText =
    glossaryDraft ??
    chinese?.glossary
      .map(({ term, expansions }) => `${term} = ${expansions.join(", ")}`)
      .join("\n") ??
    "";

  async function runAction(action: "directory" | "sync" | "glossary") {
    setBusy(true);
    setFeedback("");
    try {
      if (action === "glossary") {
        await persistGlossary();
      } else if (action === "directory") {
        await saveJson("/api/manage/admin/orgmesh/directory", "PUT", {
          enabled: true,
          credential_id: Number(currentCredential),
        });
        await refreshStatus();
      } else {
        await saveJson("/api/manage/admin/orgmesh/directory/sync", "POST");
        await refreshStatus();
      }
      setFeedback(t("saved"));
    } catch {
      setFeedback(t("failed"));
    } finally {
      setBusy(false);
    }
  }
  async function persistGlossary() {
    const glossary = glossaryText
      .split("\n")
      .filter((line) => line.trim())
      .map((line) => {
        const split = line.indexOf("=");
        if (split <= 0) throw new Error("Invalid glossary line");
        return {
          term: line.slice(0, split).trim(),
          expansions: line
            .slice(split + 1)
            .split(/[,，]/)
            .map((value) => value.trim())
            .filter(Boolean),
        };
      });
    await saveJson("/api/manage/admin/chinese-retrieval", "PUT", {
      enabled: true,
      glossary,
      max_expansions: chinese?.max_expansions ?? 8,
    });
    await refreshChinese();
    setGlossaryDraft(null);
  }
  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        icon={SvgSettings}
        title={t("title")}
        description={t("description")}
        divider
      />
      <SettingsLayouts.Body>
        <div className="flex flex-col gap-6 w-full max-w-3xl">
          {statusError || chineseError ? (
            <Text color="status-error-05">{t("loadError")}</Text>
          ) : null}
          {status ? (
            <Text color="text-03">
              {status.local_demo_access ? t("demoMode") : t("privateMode")}
            </Text>
          ) : (
            <Text>{t("loading")}</Text>
          )}
          <div className="flex flex-col gap-3 rounded-16 border border-border-01 p-5">
            <Text as="h2" font="heading-h3">
              {t("searchTitle")}
            </Text>
            <Text color="text-03">
              {status
                ? t(status.search_enabled ? "searchReady" : "searchMissing")
                : t("loading")}
            </Text>
            <div className="flex flex-wrap gap-2">
              <Button href="/admin/connectors/feishu">
                {t("connectFeishu")}
              </Button>
              <Button href="/admin/indexing/status" prominence="secondary">
                {t("syncStatus")}
              </Button>
              <Button href="/admin/language-models" prominence="secondary">
                {t("models")}
              </Button>
            </div>
          </div>
          <div className="flex flex-col gap-3 rounded-16 border border-border-01 p-5">
            <Text as="h2" font="heading-h3">
              {t("identityTitle")}
            </Text>
            <Text color="text-03">{t("identityDescription")}</Text>
            <Text>{t("ssoCount", { count: status?.sso_providers ?? 0 })}</Text>
            <div className="flex flex-wrap gap-2">
              <Button href="/admin/sso-providers" prominence="secondary">
                {t("sso")}
              </Button>
              <Button href="/admin/users" prominence="secondary">
                {t("employees")}
              </Button>
            </div>
            <label htmlFor="directory-credential">
              <Text>{t("credential")}</Text>
            </label>
            <InputSelect
              value={currentCredential}
              onValueChange={setCredentialId}
            >
              <InputSelect.Trigger
                id="directory-credential"
                placeholder={t("credentialPlaceholder")}
              />
              <InputSelect.Content>
                {(credentials ?? [])
                  .filter((item) => item.source === "feishu")
                  .map((item) => (
                    <InputSelect.Item key={item.id} value={String(item.id)}>
                      {item.name || t("credentialId", { id: item.id })}
                    </InputSelect.Item>
                  ))}
              </InputSelect.Content>
            </InputSelect>
            <Text color="text-03">
              {t("directoryStatus", {
                count: status?.directory_users ?? 0,
                time: status?.directory_last_sync
                  ? format.dateTime(new Date(status.directory_last_sync), {
                      dateStyle: "short",
                      timeStyle: "short",
                    })
                  : t("never"),
              })}
            </Text>
            <div className="flex flex-wrap gap-2">
              <Button
                disabled={busy || !currentCredential || !status}
                onClick={() => runAction("directory")}
              >
                {t("saveDirectory")}
              </Button>
              <Button
                disabled={busy || !status?.directory_config.enabled}
                prominence="secondary"
                onClick={() => runAction("sync")}
              >
                {t("syncDirectory")}
              </Button>
            </div>
          </div>
          <div className="flex flex-col gap-3 rounded-16 border border-border-01 p-5">
            <Text as="h2" font="heading-h3">
              {t("chineseTitle")}
            </Text>
            <Text color="text-03">{t("chineseDescription")}</Text>
            <label htmlFor="enterprise-glossary">
              <Text>{t("glossary")}</Text>
            </label>
            <InputTextArea
              id="enterprise-glossary"
              rows={6}
              value={glossaryText}
              onChange={(event) => setGlossaryDraft(event.target.value)}
              placeholder={t("glossaryPlaceholder")}
            />
            <Button
              disabled={busy || !chinese}
              onClick={() => runAction("glossary")}
            >
              {t("saveGlossary")}
            </Button>
          </div>
          {feedback ? <Text role="status">{feedback}</Text> : null}
        </div>
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
