import {
  PRESENTON_API,
  isPresentationId,
} from "@/sections/workspace/presentations/types";

export const HISTORY_PAGE_SIZE = 20;
export const HISTORY_MAX_PAGE = 5000;
export type PresentationTaskStatus =
  | "submitting"
  | "pending"
  | "completed"
  | "error";
export type HistoryStatusFilter = "all" | PresentationTaskStatus;
export type OwnedPresentationKey = readonly [string, string];

export interface PresentationHistoryTask {
  platform_task_id: string;
  task_id: string | null;
  presentation_id: string | null;
  status: PresentationTaskStatus;
  project_id: number | null;
  source_chat_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface HistoryProject {
  id: number;
  name: string;
}

export function ownedPresentationKey(
  url: string,
  owner: string | undefined
): OwnedPresentationKey | null {
  return owner ? [url, owner] : null;
}

export function historyPageUrl(
  page: number,
  status: HistoryStatusFilter
): string {
  if (!Number.isSafeInteger(page) || page < 0 || page > HISTORY_MAX_PAGE) {
    throw new RangeError("History page is outside the supported range");
  }
  const query = new URLSearchParams({
    limit: String(HISTORY_PAGE_SIZE + 1),
    offset: String(page * HISTORY_PAGE_SIZE),
  });
  if (status !== "all") query.set("status", status);
  return `${PRESENTON_API}/history?${query}`;
}

export function sourceChatHref(id: string | null | undefined): string | null {
  return id && isPresentationId(id)
    ? `/app?chatId=${encodeURIComponent(id)}`
    : null;
}

export function projectHistoryHref(id: number): string | null {
  return Number.isSafeInteger(id) && id > 0 ? `/app?projectId=${id}` : null;
}
