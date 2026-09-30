"use client";

import { useState } from "react";
import useSWR from "swr";
import { useFormatter, useTranslations } from "next-intl";
import { Button, InputTypeIn, Text } from "@opal/components";
import {
  SvgArrowUpRight,
  SvgFileText,
  SvgGlobe,
  SvgSearch,
  SvgSimpleLoader,
} from "@opal/icons";
import { useSettings } from "@/lib/settings/hooks";
import useCCPairs from "@/hooks/useCCPairs";
import { getSourceDisplayName } from "@/lib/sources";
import { ValidSources } from "@/lib/types";

interface SearchResult {
  citation_id: number | null;
  title: string;
  content: string;
  link: string | null;
  source_type: ValidSources;
  updated_at: string | null;
}
interface SearchResponse {
  results: SearchResult[];
}
interface SearchQuery {
  query: string;
  sources: string[] | null;
}

async function searchDocuments([, request]: readonly [
  string,
  SearchQuery,
]): Promise<SearchResponse> {
  const response = await fetch("/api/orgmesh/search", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  if (!response.ok)
    throw new Error(`Search request failed (${response.status})`);
  return response.json();
}

interface WorkspaceSearchProps {
  initialQuery: string;
}

export default function WorkspaceSearch({
  initialQuery,
}: WorkspaceSearchProps) {
  const t = useTranslations("workspace");
  const formatter = useFormatter();
  const {
    vectorDbEnabled,
    isLoading: settingsLoading,
    error: settingsError,
  } = useSettings();
  const {
    ccPairs,
    isLoading: sourcesLoading,
    error: sourcesError,
  } = useCCPairs(vectorDbEnabled);
  const [query, setQuery] = useState(initialQuery);
  const [sources, setSources] = useState<string[]>([]);
  const [submitted, setSubmitted] = useState<SearchQuery | null>(
    initialQuery.trim() ? { query: initialQuery.trim(), sources: null } : null
  );
  const available = vectorDbEnabled && ccPairs.length > 0;
  const { data, error, isLoading, mutate } = useSWR(
    submitted && available ? (["orgmesh-search", submitted] as const) : null,
    searchDocuments,
    {
      revalidateOnFocus: false,
      revalidateOnReconnect: false,
      shouldRetryOnError: false,
    }
  );
  const sourceTypes = Array.from(new Set(ccPairs.map((pair) => pair.source)));
  const loading = settingsLoading || sourcesLoading;

  function sourceLabel(source: ValidSources) {
    if (
      source === "file" ||
      source === "user_file" ||
      source === "web" ||
      source === "feishu"
    ) {
      return t(`search.sources.${source}`);
    }
    return getSourceDisplayName(source) ?? source;
  }

  function submit() {
    if (!available || !query.trim()) return;
    setSubmitted({
      query: query.trim(),
      sources: sources.length ? sources : null,
    });
  }

  return (
    <div className="workspace-search" data-testid="Workspace/search">
      <div className="workspace-page-heading">
        <Text as="h1" font="heading-h2">
          {t("search.title")}
        </Text>
        <Text as="p" font="main-content-muted" color="text-03">
          {t("search.description")}
        </Text>
      </div>
      <form
        className="workspace-search-form"
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        <InputTypeIn
          searchIcon
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder={t("search.placeholder")}
          aria-label={t("search.placeholder")}
          maxLength={2048}
          rightChildren={
            <Button
              type="submit"
              icon={SvgArrowUpRight}
              disabled={!query.trim() || !available || isLoading}
              aria-label={t("search.title")}
            />
          }
        />
      </form>
      <div className="workspace-search-filters">
        <Button
          prominence={sources.length ? "tertiary" : "secondary"}
          onClick={() => setSources([])}
        >
          {t("search.allSources")}
        </Button>
        {sourceTypes.map((source) => (
          <Button
            key={source}
            prominence={sources.includes(source) ? "secondary" : "tertiary"}
            onClick={() =>
              setSources((previous) =>
                previous.includes(source)
                  ? previous.filter((item) => item !== source)
                  : [...previous, source]
              )
            }
          >
            {sourceLabel(source)}
          </Button>
        ))}
        <Button
          href="/admin/indexing/status"
          icon={SvgGlobe}
          prominence="tertiary"
        >
          {t("search.manageSources")}
        </Button>
      </div>
      {loading || isLoading ? (
        <div className="workspace-empty">
          <SvgSimpleLoader size={28} />
          <Text font="main-ui-muted">
            {t(isLoading ? "search.searching" : "loading")}
          </Text>
        </div>
      ) : settingsError || sourcesError ? (
        <div className="workspace-empty">
          <Text font="main-ui-action" color="status-error-05">
            {t("loadError")}
          </Text>
        </div>
      ) : error ? (
        <div className="workspace-empty">
          <Text font="main-ui-action" color="status-error-05">
            {t("search.error")}
          </Text>
          <Button prominence="secondary" onClick={() => void mutate()}>
            {t("retry")}
          </Button>
        </div>
      ) : !available ? (
        <div className="workspace-search-empty">
          <div className="workspace-large-icon">
            <SvgSearch size={32} />
          </div>
          <Text as="h2" font="heading-h3">
            {t(!vectorDbEnabled ? "search.liteTitle" : "search.setupTitle")}
          </Text>
          <Text as="p" font="main-ui-muted" color="text-03">
            {t(
              !vectorDbEnabled
                ? "search.liteDescription"
                : "search.setupDescription"
            )}
          </Text>
          <div className="flex flex-wrap justify-center gap-2">
            <Button href="/app/settings/workspace" icon={SvgArrowUpRight}>
              {t("search.setupAction")}
            </Button>
            <Button href="/app" prominence="secondary">
              {t("search.backToAssistant")}
            </Button>
          </div>
        </div>
      ) : data ? (
        <section className="workspace-search-results">
          <Text font="secondary-body" color="text-03">
            {t("search.resultCount", { count: data.results.length })}
          </Text>
          {data.results.length ? (
            data.results.map((result, index) => (
              <article
                className="workspace-search-result"
                key={`${result.citation_id}-${index}`}
              >
                <div className="flex items-center gap-2">
                  <SvgFileText size={18} />
                  <Text font="secondary-body" color="text-03">
                    {sourceLabel(result.source_type)}
                  </Text>
                  {result.updated_at && (
                    <Text font="secondary-body" color="text-03">
                      {formatter.dateTime(new Date(result.updated_at), {
                        dateStyle: "medium",
                      })}
                    </Text>
                  )}
                </div>
                <Text as="h2" font="heading-h3">
                  {result.title}
                </Text>
                <Text as="p" font="main-ui-muted" color="text-03">
                  {result.content}
                </Text>
                {result.link && /^https?:\/\//i.test(result.link) && (
                  <Button
                    href={result.link}
                    icon={SvgArrowUpRight}
                    prominence="tertiary"
                  >
                    {t("search.openSource")}
                  </Button>
                )}
              </article>
            ))
          ) : (
            <div className="workspace-empty">
              <Text font="main-ui-action">{t("search.noResults")}</Text>
              <Text font="secondary-body" color="text-03">
                {t("search.tryAgain")}
              </Text>
            </div>
          )}
        </section>
      ) : (
        <div className="workspace-empty">
          <SvgSearch size={28} />
          <Text font="main-ui-muted">{t("search.start")}</Text>
        </div>
      )}
    </div>
  );
}
