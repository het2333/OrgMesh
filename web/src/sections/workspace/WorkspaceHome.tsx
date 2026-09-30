"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useFormatter, useTranslations } from "next-intl";
import { Button, InputTypeIn, Text } from "@opal/components";
import {
  SvgArrowUpRight,
  SvgBubbleText,
  SvgFileText,
  SvgOnyxOctagon,
  SvgSearch,
  SvgSimpleLoader,
  SvgSparkle,
} from "@opal/icons";
import { useUser } from "@/providers/UserProvider";
import { useLLMProviders } from "@/lib/languageModels/hooks";
import { hasVisibleLLMModel } from "@/lib/languageModels/utils";
import useChatSessions from "@/hooks/useChatSessions";
import { useAgents } from "@/lib/agents/hooks";
import { routeWithQuery } from "@/lib/routes";
import { SEARCH_PARAM_NAMES } from "@/app/app/services/searchParams";
import { cn } from "@opal/utils";

export default function WorkspaceHome() {
  const t = useTranslations("workspace");
  const formatter = useFormatter();
  const router = useRouter();
  const { user } = useUser();
  const {
    llmProviders,
    isLoading: modelsLoading,
    error: modelsError,
  } = useLLMProviders();
  const {
    chatSessions,
    isLoading: chatsLoading,
    error: chatsError,
  } = useChatSessions();
  const { agents } = useAgents();
  const [query, setQuery] = useState("");
  const [mode, setMode] = useState<"assistant" | "search">("assistant");
  const modelReady = hasVisibleLLMModel(llmProviders);
  const featured = agents.filter((agent) => !agent.builtin_persona).slice(0, 3);

  function submit() {
    if (!query.trim()) return;
    if (mode === "search") {
      router.push(
        routeWithQuery("/app/search", {
          [SEARCH_PARAM_NAMES.SEARCH_QUERY]: query.trim(),
        })
      );
    } else if (modelReady) {
      router.push(
        routeWithQuery("/app", {
          [SEARCH_PARAM_NAMES.USER_PROMPT]: query.trim(),
          [SEARCH_PARAM_NAMES.SUBMIT_ON_LOAD]: "true",
        })
      );
    }
  }

  return (
    <div className="workspace-home" data-testid="Workspace/home">
      <section className="workspace-hero">
        <div className="workspace-eyebrow">
          <SvgSparkle size={16} />
          <Text font="secondary-action" color="inherit">
            {t("home.eyebrow")}
          </Text>
        </div>
        <Text as="h1" font="heading-h1" color="text-05">
          {t("home.greeting", {
            name: user?.personalization?.name || t("brand"),
          })}
        </Text>
        <Text as="p" font="main-content-muted" color="text-03">
          {t("home.description")}
        </Text>
        <div className="workspace-composer">
          <form
            onSubmit={(event) => {
              event.preventDefault();
              submit();
            }}
            className="w-full"
          >
            <InputTypeIn
              variant="internal"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder={t(
                mode === "assistant"
                  ? "home.askPlaceholder"
                  : "search.placeholder"
              )}
              aria-label={t("home.askPlaceholder")}
              maxLength={2048}
            />
            <div className="workspace-composer-toolbar">
              <div className="flex items-center gap-1">
                <Button
                  icon={SvgSparkle}
                  prominence={mode === "assistant" ? "secondary" : "tertiary"}
                  onClick={() => setMode("assistant")}
                >
                  {t("assistant")}
                </Button>
                <Button
                  icon={SvgSearch}
                  prominence={mode === "search" ? "secondary" : "tertiary"}
                  onClick={() => setMode("search")}
                >
                  {t("search.title")}
                </Button>
              </div>
              <Button
                type="submit"
                icon={SvgArrowUpRight}
                disabled={
                  !query.trim() || (mode === "assistant" && !modelReady)
                }
                aria-label={t("send")}
                tooltip={t("send")}
              />
            </div>
          </form>
        </div>
        <div className="workspace-prompts">
          {(["summarize", "plan", "research"] as const).map((key) => (
            <Button
              key={key}
              prominence="tertiary"
              onClick={() => {
                setMode("assistant");
                setQuery(t(`home.prompts.${key}.query`));
              }}
            >
              {t(`home.prompts.${key}.label`)}
            </Button>
          ))}
        </div>
      </section>

      {modelsLoading ? (
        <div className="workspace-loading">
          <SvgSimpleLoader size={20} />
          <Text font="secondary-body" color="text-03">
            {t("loading")}
          </Text>
        </div>
      ) : (
        (!modelReady || modelsError) && (
          <div className="workspace-setup">
            <div className="flex items-start gap-3">
              <div className="workspace-icon-tile">
                <SvgSparkle size={20} />
              </div>
              <div className="flex flex-col gap-1">
                <Text font="main-ui-action">
                  {t(modelsError ? "loadError" : "home.setupTitle")}
                </Text>
                <Text font="secondary-body" color="text-03">
                  {t("home.setupDescription")}
                </Text>
              </div>
            </div>
            <Button
              href="/admin/language-models"
              prominence="secondary"
              icon={SvgArrowUpRight}
            >
              {t("configureModels")}
            </Button>
          </div>
        )
      )}

      <div className="workspace-section-heading">
        <Text as="h2" font="heading-h3">
          {t("home.explore")}
        </Text>
        <Text font="secondary-body" color="text-03">
          {t("home.exploreDescription")}
        </Text>
      </div>
      <div className="workspace-shortcut-grid">
        {(
          [
            { key: "search", href: "/app/search", icon: SvgSearch },
            { key: "agents", href: "/app/agents", icon: SvgOnyxOctagon },
            { key: "settings", href: "/app/settings", icon: SvgFileText },
          ] as const
        ).map(({ key, href, icon: Icon }) => (
          <Link
            key={key}
            href={href}
            className={cn("workspace-shortcut", `workspace-shortcut-${key}`)}
          >
            <div className="workspace-shortcut-top">
              <span className="workspace-icon-tile">
                <Icon size={21} />
              </span>
              <SvgArrowUpRight size={16} />
            </div>
            <Text font="main-ui-action">
              {t(`home.shortcuts.${key}.title`)}
            </Text>
            <Text as="p" font="secondary-body" color="text-03">
              {t(`home.shortcuts.${key}.description`)}
            </Text>
          </Link>
        ))}
      </div>
      <section className="workspace-recent">
        <div className="workspace-section-heading">
          <Text as="h2" font="heading-h3">
            {t("home.recent")}
          </Text>
          <Text font="secondary-body" color="text-03">
            {t("home.recentDescription")}
          </Text>
        </div>
        {chatsLoading ? (
          <div className="workspace-loading">
            <SvgSimpleLoader size={20} />
            <Text font="main-ui-muted">{t("loading")}</Text>
          </div>
        ) : chatsError ? (
          <Text as="p" font="main-ui-muted" color="status-error-05">
            {t("loadError")}
          </Text>
        ) : chatSessions.length ? (
          <div className="workspace-recent-list">
            {chatSessions.slice(0, 5).map((chat) => (
              <Link
                key={chat.id}
                className="workspace-recent-row"
                href={routeWithQuery("/app", {
                  [SEARCH_PARAM_NAMES.CHAT_ID]: chat.id,
                })}
              >
                <SvgBubbleText size={18} />
                <Text font="main-ui-body">
                  {chat.name || t("untitledChat")}
                </Text>
                <Text font="secondary-body" color="text-03">
                  {formatter.dateTime(new Date(chat.time_created), {
                    month: "short",
                    day: "numeric",
                  })}
                </Text>
                <SvgArrowUpRight size={16} />
              </Link>
            ))}
          </div>
        ) : (
          <div className="workspace-empty">
            <SvgBubbleText size={26} />
            <Text font="main-ui-action">{t("home.emptyTitle")}</Text>
            <Text font="secondary-body" color="text-03">
              {t("home.emptyDescription")}
            </Text>
          </div>
        )}
      </section>
      {featured.length > 0 && (
        <section>
          <div className="workspace-section-heading">
            <Text as="h2" font="heading-h3">
              {t("agents")}
            </Text>
            <Button href="/app/agents" prominence="tertiary">
              {t("viewAll")}
            </Button>
          </div>
          <div className="workspace-shortcut-grid">
            {featured.map((agent) => (
              <Link
                key={agent.id}
                className="workspace-shortcut"
                href={routeWithQuery("/app", {
                  [SEARCH_PARAM_NAMES.AGENT_ID]: agent.id,
                })}
              >
                <SvgOnyxOctagon size={20} />
                <Text font="main-ui-action">{agent.name}</Text>
                <Text font="secondary-body" color="text-03">
                  {agent.description}
                </Text>
              </Link>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
