"use client";

import { useState } from "react";
import useSWR from "swr";
import { useFormatter, useTranslations } from "next-intl";
import { Button, IconLoader, Text } from "@opal/components";
import { IllustrationContent } from "@opal/layouts";
import {
  SvgArrowLeft,
  SvgArrowRight,
  SvgBubbleText,
  SvgFolder,
  SvgHistory,
  SvgRefreshCw,
  SvgSlidesFile,
} from "@opal/icons";
import {
  errorHandlingFetcher,
  isAuthStatusError,
  isNotFoundError,
  skipRetryOnAuthError,
} from "@/lib/fetcher";
import { useUser } from "@/providers/UserProvider";
import {
  HISTORY_PAGE_SIZE,
  HISTORY_MAX_PAGE,
  historyPageUrl,
  ownedPresentationKey,
  projectHistoryHref,
  sourceChatHref,
  type HistoryProject,
  type HistoryStatusFilter,
  type OwnedPresentationKey,
  type PresentationHistoryTask,
} from "@/sections/workspace/presentations/history";
import {
  PRESENTON_JOBS_KEY,
  PRESENTON_LIBRARY_KEY,
  PRESENTON_TIME_ZONE,
  isPresentationId,
  presentationEditorHref,
  type PresentationJob,
  type WorkspacePresentation,
} from "@/sections/workspace/presentations/types";

async function fetchOwned<T>([url]: OwnedPresentationKey): Promise<T> {
  return errorHandlingFetcher<T>(url);
}

interface ProvenanceLinksProps {
  sourceChatId: string | null | undefined;
  projectId: number | null | undefined;
  projects: readonly HistoryProject[];
}

function ProvenanceLinks({
  sourceChatId,
  projectId,
  projects,
}: ProvenanceLinksProps) {
  const t = useTranslations("workspace.tools.history");
  const sourceHref = sourceChatHref(sourceChatId);
  const project = projects.find((item) => item.id === projectId);
  const projectHref = project ? projectHistoryHref(project.id) : null;
  return (
    <div className="workspace-history-provenance">
      {project && projectHref && (
        <Button
          icon={SvgFolder}
          href={projectHref}
          prominence="tertiary"
          size="sm"
        >
          {project.name}
        </Button>
      )}
      {sourceHref && (
        <Button
          icon={SvgBubbleText}
          href={sourceHref}
          prominence="tertiary"
          size="sm"
        >
          {t("openSource")}
        </Button>
      )}
      {!sourceHref && (
        <Text font="secondary-body" color="text-03">
          {t("unlinked")}
        </Text>
      )}
    </div>
  );
}

const FILTERS: readonly HistoryStatusFilter[] = [
  "all",
  "submitting",
  "pending",
  "completed",
  "error",
];

export default function PresentationHistory() {
  const t = useTranslations("workspace.tools.history");
  const formatter = useFormatter();
  const { user, isUserLoading } = useUser();
  const owner = isUserLoading ? undefined : user?.id;
  const [view, setView] = useState<"tasks" | "presentations">("tasks");
  const [taskPage, setTaskPage] = useState(0);
  const [deckPage, setDeckPage] = useState(0);
  const [filter, setFilter] = useState<HistoryStatusFilter>("all");
  const [paginationOwner, setPaginationOwner] = useState(owner);
  if (!isUserLoading && paginationOwner !== owner) {
    // Reset this view's paging when the resolved account changes.
    setPaginationOwner(owner);
    setTaskPage(0);
    setDeckPage(0);
    setFilter("all");
  }
  const historyKey = ownedPresentationKey(
    historyPageUrl(taskPage, filter),
    owner
  );
  const {
    data: tasks,
    error: taskError,
    isLoading: tasksLoading,
    mutate: refreshTasks,
  } = useSWR<PresentationHistoryTask[]>(historyKey, fetchOwned, {
    onErrorRetry: skipRetryOnAuthError,
    errorRetryCount: 0,
    refreshInterval: (data) =>
      data?.some((task) => task.status === "pending") ? 3000 : 30000,
  });
  const {
    data: decks,
    error: deckError,
    isLoading: decksLoading,
    mutate: refreshDecks,
  } = useSWR<WorkspacePresentation[]>(
    ownedPresentationKey(PRESENTON_LIBRARY_KEY, owner),
    fetchOwned,
    {
      onErrorRetry: skipRetryOnAuthError,
      errorRetryCount: 0,
      refreshInterval: 30000,
    }
  );
  const {
    data: jobs,
    error: liveError,
    mutate: refreshJobs,
  } = useSWR<PresentationJob[]>(
    ownedPresentationKey(PRESENTON_JOBS_KEY, owner),
    fetchOwned,
    {
      onErrorRetry: skipRetryOnAuthError,
      errorRetryCount: 0,
      refreshInterval: (data) =>
        data?.some((job) => job.status === "pending") ? 3000 : 30000,
      onSuccess: () => {
        void refreshTasks();
      },
    }
  );
  const { data: projects, error: projectError } = useSWR<HistoryProject[]>(
    ownedPresentationKey("/api/user/projects", owner),
    fetchOwned,
    { onErrorRetry: skipRetryOnAuthError, errorRetryCount: 0 }
  );

  function dateLabel(value: string): string {
    const date = new Date(value);
    return Number.isFinite(date.getTime())
      ? formatter.dateTime(date, {
          timeZone: PRESENTON_TIME_ZONE,
          year: "numeric",
          month: "short",
          day: "numeric",
          hour: "numeric",
          minute: "numeric",
        })
      : t("timeUnavailable");
  }

  async function refresh() {
    // Engine reads synchronize the platform first, then refresh durable history.
    await Promise.allSettled([refreshJobs(), refreshDecks()]);
    await refreshTasks();
  }

  if (isUserLoading)
    return (
      <div className="workspace-loading" role="status">
        <IconLoader size={20} />
        <Text font="main-ui-muted">{t("loading")}</Text>
      </div>
    );
  if (
    !owner ||
    [taskError, deckError, liveError, projectError].some(isAuthStatusError)
  ) {
    return (
      <div className="workspace-presentation-empty" role="alert">
        <IllustrationContent
          title={t("authTitle")}
          description={t("authDescription")}
        />
      </div>
    );
  }

  const ownedProjects = projectError ? [] : (projects ?? []);
  const visibleDecks = (deckError ? [] : (decks ?? [])).filter((deck) =>
    isPresentationId(deck.id)
  );
  const pendingDecks = new Set(
    jobs
      ?.filter((job) => job.status === "pending")
      .map((job) => job.data?.presentation_id)
  );
  const titleByDeck = new Map(
    visibleDecks.map((deck) => [deck.id, deck.title])
  );
  const historyDisabled = isNotFoundError(taskError);
  const loading = view === "tasks" ? tasksLoading : decksLoading;
  const error = view === "tasks" ? taskError : deckError;
  const rows =
    view === "tasks"
      ? (tasks ?? []).slice(0, HISTORY_PAGE_SIZE)
      : visibleDecks.slice(
          deckPage * HISTORY_PAGE_SIZE,
          (deckPage + 1) * HISTORY_PAGE_SIZE
        );
  const page = view === "tasks" ? taskPage : deckPage;
  const hasNext =
    view === "tasks"
      ? (tasks?.length ?? 0) > HISTORY_PAGE_SIZE && taskPage < HISTORY_MAX_PAGE
      : (deckPage + 1) * HISTORY_PAGE_SIZE < visibleDecks.length;

  return (
    <div
      className="workspace-tools workspace-history"
      data-testid="Workspace/history"
    >
      <div className="workspace-history-heading">
        <div className="workspace-page-heading">
          <Text as="h1" font="heading-h2">
            {t("title")}
          </Text>
          <Text as="p" font="main-ui-muted" color="text-03">
            {t("description")}
          </Text>
        </div>
        <div className="workspace-history-actions">
          <Button href="/app/tools" icon={SvgArrowLeft} prominence="tertiary">
            {t("backToTools")}
          </Button>
          <Button
            icon={SvgRefreshCw}
            prominence="secondary"
            onClick={() => void refresh()}
          >
            {t("refresh")}
          </Button>
        </div>
      </div>
      <div className="workspace-history-controls" aria-label={t("viewsLabel")}>
        <Button
          icon={SvgHistory}
          prominence={view === "tasks" ? "secondary" : "tertiary"}
          aria-pressed={view === "tasks"}
          onClick={() => setView("tasks")}
        >
          {t("tasksTab")}
        </Button>
        <Button
          icon={SvgSlidesFile}
          prominence={view === "presentations" ? "secondary" : "tertiary"}
          aria-pressed={view === "presentations"}
          onClick={() => setView("presentations")}
        >
          {t("presentationsTab")}
        </Button>
      </div>
      {view === "tasks" && !historyDisabled && (
        <div
          className="workspace-history-controls"
          aria-label={t("filtersLabel")}
        >
          {FILTERS.map((status) => (
            <Button
              key={status}
              size="sm"
              prominence={filter === status ? "secondary" : "tertiary"}
              aria-pressed={filter === status}
              onClick={() => {
                setFilter(status);
                setTaskPage(0);
              }}
            >
              {t(`filter.${status}`)}
            </Button>
          ))}
        </div>
      )}
      {liveError && view === "tasks" && (
        <div className="workspace-presentation-notice" role="status">
          <Text font="main-ui-muted">{t("liveUnavailable")}</Text>
        </div>
      )}
      {historyDisabled && view === "presentations" && (
        <div className="workspace-presentation-notice" role="status">
          <Text font="main-ui-muted">{t("disabledDescription")}</Text>
        </div>
      )}
      {loading ? (
        <div className="workspace-loading" role="status">
          <IconLoader size={20} />
          <Text font="main-ui-muted">{t("loading")}</Text>
        </div>
      ) : error ? (
        <div className="workspace-presentation-empty" role="alert">
          <IllustrationContent
            title={t(
              historyDisabled && view === "tasks"
                ? "disabledTitle"
                : "errorTitle"
            )}
            description={t(
              historyDisabled && view === "tasks"
                ? "disabledDescription"
                : "errorDescription"
            )}
          />
          {!historyDisabled && (
            <Button
              prominence="secondary"
              onClick={() => {
                void (view === "tasks" ? refreshTasks() : refreshDecks());
              }}
            >
              {t("retry")}
            </Button>
          )}
        </div>
      ) : !rows.length ? (
        <div className="workspace-presentation-empty">
          <IllustrationContent
            title={t(view === "tasks" ? "emptyTasksTitle" : "emptyDecksTitle")}
            description={t(
              view === "tasks"
                ? "emptyTasksDescription"
                : "emptyDecksDescription"
            )}
          />
        </div>
      ) : view === "tasks" ? (
        <div className="workspace-presentation-job-list">
          {(tasks ?? []).slice(0, HISTORY_PAGE_SIZE).map((task) => {
            const deckId =
              task.presentation_id && isPresentationId(task.presentation_id)
                ? task.presentation_id
                : null;
            return (
              <article
                className="workspace-history-task"
                key={task.platform_task_id}
              >
                <div className="workspace-history-task-copy">
                  <Text as="h2" font="main-content-emphasis" maxLines={2}>
                    {deckId
                      ? titleByDeck.get(deckId) || t("untitled")
                      : t("taskTitle")}
                  </Text>
                  <Text
                    font="main-ui-action"
                    color={
                      task.status === "error" ? "status-error-05" : "text-04"
                    }
                  >
                    {t(`status.${task.status}`)}
                  </Text>
                  <Text font="secondary-body" color="text-03">
                    {dateLabel(task.created_at)}
                  </Text>
                  {task.status === "submitting" && (
                    <Text font="main-ui-muted" color="text-03">
                      {t("unconfirmedHint")}
                    </Text>
                  )}
                  {task.status === "error" && (
                    <Text font="main-ui-muted" color="text-03">
                      {t("failedHint")}
                    </Text>
                  )}
                  <ProvenanceLinks
                    sourceChatId={task.source_chat_id}
                    projectId={task.project_id}
                    projects={ownedProjects}
                  />
                </div>
                {deckId && task.status === "completed" && (
                  <Button
                    href={presentationEditorHref(deckId)}
                    prominence="secondary"
                    size="sm"
                  >
                    {t("openEditor")}
                  </Button>
                )}
              </article>
            );
          })}
        </div>
      ) : (
        <div className="workspace-presentation-grid">
          {visibleDecks
            .slice(
              deckPage * HISTORY_PAGE_SIZE,
              (deckPage + 1) * HISTORY_PAGE_SIZE
            )
            .map((deck) => (
              <article className="workspace-presentation-card" key={deck.id}>
                <div className="workspace-icon-tile">
                  <SvgSlidesFile size={23} />
                </div>
                <Text as="h2" font="main-content-emphasis" maxLines={2}>
                  {deck.title || t("untitled")}
                </Text>
                <Text font="secondary-body" color="text-03">
                  {t("slideCount", { count: deck.n_slides })}
                </Text>
                <Text font="secondary-body" color="text-03">
                  {dateLabel(deck.updated_at ?? deck.created_at)}
                </Text>
                <ProvenanceLinks
                  sourceChatId={deck.source_chat_id}
                  projectId={deck.project_id}
                  projects={ownedProjects}
                />
                <Button
                  href={presentationEditorHref(deck.id)}
                  prominence="secondary"
                  disabled={pendingDecks.has(deck.id)}
                >
                  {t(
                    pendingDecks.has(deck.id) ? "status.pending" : "openEditor"
                  )}
                </Button>
              </article>
            ))}
        </div>
      )}
      {!loading && !error && (
        <div
          className="workspace-history-pagination"
          aria-label={t("paginationLabel")}
        >
          <Button
            icon={SvgArrowLeft}
            prominence="secondary"
            disabled={page === 0}
            onClick={() => {
              if (view === "tasks") setTaskPage(Math.max(0, taskPage - 1));
              else setDeckPage(Math.max(0, deckPage - 1));
            }}
          >
            {t("previousPage")}
          </Button>
          <Text font="secondary-body" color="text-03">
            {t("pageNumber", { page: page + 1 })}
          </Text>
          <Button
            icon={SvgArrowRight}
            prominence="secondary"
            disabled={!hasNext}
            onClick={() => {
              if (view === "tasks") setTaskPage(taskPage + 1);
              else setDeckPage(deckPage + 1);
            }}
          >
            {t("nextPage")}
          </Button>
        </div>
      )}
    </div>
  );
}
