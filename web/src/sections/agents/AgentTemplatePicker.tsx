"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import useSWR from "swr";
import { Button, Text } from "@opal/components";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { useAgents } from "@/lib/agents/hooks";
import { useLLMProviders } from "@/lib/languageModels/hooks";
import { hasVisibleLLMModel } from "@/lib/languageModels/utils";

interface AgentTemplate {
  id: string;
  name: string;
  description: string;
  starter_message: string;
  persona_id: number | null;
}

interface AgentTemplateCatalog {
  templates: AgentTemplate[];
  document_search_available: boolean;
  search_tool_available?: boolean;
  can_install: boolean;
}

export default function AgentTemplatePicker() {
  const t = useTranslations("workspace.agentTemplates");
  const common = useTranslations("workspace");
  const router = useRouter();
  const { refresh } = useAgents();
  const {
    llmProviders,
    isLoading: modelsLoading,
    error: modelsError,
  } = useLLMProviders();
  const {
    data,
    error: loadError,
    isLoading,
    mutate,
  } = useSWR<AgentTemplateCatalog>(
    "/api/agent-templates",
    errorHandlingFetcher
  );
  const [installing, setInstalling] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function installTemplate(template: AgentTemplate) {
    setInstalling(template.id);
    setError(null);
    try {
      const response = await fetch(
        `/api/agent-templates/${encodeURIComponent(template.id)}/install`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({}),
        }
      );
      if (!response.ok) {
        const body: { detail?: string } = await response.json();
        throw new Error(body.detail || t("installFailed"));
      }
      const agent: { id: number } = await response.json();
      await Promise.all([refresh(), mutate()]);
      router.push(`/app/agents/edit/${agent.id}`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("installFailed"));
    } finally {
      setInstalling(null);
    }
  }

  return (
    <div className="flex flex-col gap-4 w-full">
      <div className="flex flex-col gap-2">
        <Text font="heading-h3">{t("title")}</Text>
        <Text font="main-ui-muted" color="text-03">
          {t("description")}
        </Text>
      </div>
      {isLoading && <Text color="text-03">{t("loading")}</Text>}
      {loadError && <Text color="status-error-05">{t("loadFailed")}</Text>}
      {data && (
        <>
          {modelsError && (
            <Text color="status-error-05">{common("loadError")}</Text>
          )}
          {!modelsLoading &&
            !modelsError &&
            !hasVisibleLLMModel(llmProviders) && (
              <Text color="text-03">{t("noModel")}</Text>
            )}
          {!data.document_search_available && (
            <Text color="text-03">{t("noDocumentSearch")}</Text>
          )}
          {data.document_search_available &&
            data.search_tool_available === false && (
              <Text color="text-03">{t("noKnowledge")}</Text>
            )}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {data.templates.map((template) => (
              <div
                key={template.id}
                className="flex flex-col gap-3 rounded-lg border border-border-01 p-4 background-neutral-00"
              >
                <Text font="main-ui-action">{template.name}</Text>
                <Text font="main-ui-muted" color="text-03">
                  {template.description}
                </Text>
                <div className="mt-auto flex flex-wrap gap-2">
                  {template.persona_id !== null ? (
                    <>
                      <Button
                        prominence="secondary"
                        href={`/app?agentId=${template.persona_id}`}
                      >
                        {t("open")}
                      </Button>
                      {data.can_install && (
                        <Button
                          prominence="tertiary"
                          href={`/app/agents/edit/${template.persona_id}`}
                        >
                          {t("configure")}
                        </Button>
                      )}
                    </>
                  ) : (
                    <Button
                      prominence="secondary"
                      disabled={!data.can_install || installing !== null}
                      onClick={() => installTemplate(template)}
                      tooltip={
                        !data.can_install ? t("adminRequired") : undefined
                      }
                    >
                      {t(installing === template.id ? "installing" : "install")}
                    </Button>
                  )}
                </div>
              </div>
            ))}
          </div>
        </>
      )}
      {error && <Text color="status-error-05">{error}</Text>}
    </div>
  );
}
