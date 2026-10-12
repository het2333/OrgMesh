"use client";

import useSWR, { useSWRConfig, type KeyedMutator } from "swr";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { useUser } from "@/providers/UserProvider";
import { Permission } from "@/lib/types";
import { STATIC_BRANDING } from "@/lib/orgmesh-enterprise/staticBranding";
import {
  ENTERPRISE_API,
  PRIVATE_CACHE_PREFIX,
  fetchOrgMeshBranding,
  fetchEnterpriseCapabilities,
  fetchEnterpriseContext,
  fetchEnterpriseAudit,
  fetchEnterpriseUsage,
  EnterpriseApiError,
  isEnterprisePrivateKey,
} from "@/lib/orgmesh-enterprise/svc";
import type {
  BrandingView,
  EnterpriseCapabilities,
  EnterpriseContext,
  AuditPage,
  AuditQuery,
  UsageQuery,
  UsageSummary,
  UsageCoverage,
} from "@/lib/orgmesh-enterprise/types";

export interface BrandingState {
  data: BrandingView;
  source: BrandingView["source"];
  isLoading: boolean;
  error: Error | undefined;
  reload: KeyedMutator<BrandingView>;
}

export function useOrgMeshBranding(): BrandingState {
  const { data, error, isLoading, mutate } = useSWR<BrandingView>(
    `${ENTERPRISE_API}/branding`,
    fetchOrgMeshBranding,
    {
      fallbackData: STATIC_BRANDING,
      revalidateOnFocus: false,
      errorRetryInterval: 5000,
    }
  );
  const branding = data ?? STATIC_BRANDING;
  return {
    data: branding,
    source: branding.source,
    isLoading,
    error,
    reload: mutate,
  };
}

export function useEnterpriseCapabilities() {
  return useSWR<EnterpriseCapabilities>(
    `${ENTERPRISE_API}/capabilities`,
    fetchEnterpriseCapabilities,
    { revalidateOnFocus: false, shouldRetryOnError: false }
  );
}

export function useEnterpriseContext() {
  const { user, userResolution, permissions } = useUser();
  const canAdmin =
    userResolution === "resolved" &&
    !!user &&
    permissions.includes(Permission.FULL_ADMIN_PANEL_ACCESS);
  const state = useSWR<EnterpriseContext>(
    canAdmin ? [PRIVATE_CACHE_PREFIX, "context", user.id] : null,
    fetchEnterpriseContext,
    { revalidateOnFocus: true, shouldRetryOnError: false }
  );
  const context =
    canAdmin && state.data?.user_id === user.id ? state.data : undefined;
  const mismatch = canAdmin && state.data && !context;
  return {
    ...state,
    // Cached IDs preserve a read-only draft; only data grants usable context.
    cachedData: context,
    data: state.error ? undefined : context,
    canAdmin,
    error:
      state.error ??
      (mismatch
        ? new Error(
            "Authenticated organization context does not match the current actor"
          )
        : undefined),
  };
}

export interface AuditState {
  data: AuditPage | undefined;
  isLoading: boolean;
  error: Error | undefined;
  canAdmin: boolean;
  reload: () => Promise<void>;
}

export function useEnterpriseAudit(query: AuditQuery): AuditState {
  const context = useEnterpriseContext();
  const capabilities = useEnterpriseCapabilities();
  const { data, error, isLoading, mutate } = useSWR<AuditPage>(
    context.data && capabilities.data?.audit_enabled
      ? [
          PRIVATE_CACHE_PREFIX,
          "audit",
          context.data.user_id,
          context.data.tenant_id,
          query,
        ]
      : null,
    () => fetchEnterpriseAudit(query),
    {
      revalidateOnFocus: true,
      shouldRetryOnError: false,
      keepPreviousData: false,
    }
  );
  return {
    data: context.data ? data : undefined,
    error: context.error ?? error,
    isLoading: context.isLoading || isLoading,
    canAdmin: context.canAdmin,
    reload: async () => {
      await context.mutate();
      await mutate();
    },
  };
}

/** Mounted in the user provider, so leaving an admin page does not retain private data. */
export function useEnterpriseCacheLifecycle(actorId: string | undefined) {
  const { mutate } = useSWRConfig();
  const previous = useRef(actorId);
  useEffect(() => {
    if (previous.current !== actorId) {
      void mutate(
        (key) =>
          isEnterprisePrivateKey(key) &&
          Array.isArray(key) &&
          key[2] !== actorId,
        undefined,
        { revalidate: false }
      );
      previous.current = actorId;
    }
  }, [actorId, mutate]);
}

export interface UsageState {
  data: UsageSummary | undefined;
  coverage: UsageCoverage | null;
  lastPublishedAt: string | null;
  stale: boolean;
  unavailable: boolean;
  activationBoundary: string | null;
  activatedAt: string | null;
  waiting: boolean;
  isLoading: boolean;
  canAdmin: boolean;
  error: Error | undefined;
  reload: () => Promise<void>;
}

const USAGE_REFRESH_INTERVAL_MS = 15_000;
const USAGE_STALE_AFTER_MS = 120_000;

export function useEnterpriseUsage(query: UsageQuery): UsageState {
  const context = useEnterpriseContext();
  const capabilities = useEnterpriseCapabilities();
  const { mutate: clearPrivateCache } = useSWRConfig();
  const scope =
    context.data && !capabilities.error && capabilities.data?.usage_enabled
      ? JSON.stringify([context.data.user_id, context.data.tenant_id])
      : undefined;
  const activeScope = useRef(scope);
  // Fence pending requests before they can refill a departed session's cache.
  useLayoutEffect(() => {
    activeScope.current = scope;
    return () => {
      activeScope.current = undefined;
    };
  }, [scope]);
  useEffect(() => {
    if (!context.data) return;
    const { user_id, tenant_id } = context.data;
    void clearPrivateCache(
      (key) =>
        isEnterprisePrivateKey(key) &&
        key[1] === "usage" &&
        (key[2] !== user_id || key[3] !== tenant_id),
      undefined,
      { revalidate: false }
    );
  }, [context.data, clearPrivateCache]);
  const state = useSWR<UsageSummary>(
    scope && context.data
      ? [
          PRIVATE_CACHE_PREFIX,
          "usage",
          context.data.user_id,
          context.data.tenant_id,
          query.start,
          query.end,
          query.group_by,
        ]
      : null,
    async () => {
      const response = await fetchEnterpriseUsage(query);
      if (activeScope.current !== scope)
        throw new Error("Usage session changed");
      return response;
    },
    {
      revalidateOnFocus: true,
      shouldRetryOnError: false,
      keepPreviousData: false,
    }
  );
  const authorityFailure =
    state.error instanceof EnterpriseApiError &&
    (state.error.status === 401 || state.error.status === 403);
  // Schedule only after the previous request settles, including failed requests.
  useEffect(() => {
    if (!scope || authorityFailure || state.isValidating) return;
    const timer = setTimeout(
      () => void state.mutate(),
      USAGE_REFRESH_INTERVAL_MS
    );
    return () => clearTimeout(timer);
  }, [
    scope,
    authorityFailure,
    query.start,
    query.end,
    query.group_by,
    state.isValidating,
    state.mutate,
  ]);

  const snapshot = scope && !authorityFailure ? state.data : undefined;
  const data =
    snapshot && (snapshot.status === "ready" || snapshot.status === "stale")
      ? snapshot
      : undefined;
  const error = context.error ?? capabilities.error ?? state.error;
  const [now, setNow] = useState(Date.now);
  const publishedAt = data?.published_at;
  // Publication age advances even while a refresh is stalled or Go is unavailable.
  useEffect(() => {
    if (!scope || !publishedAt) return;
    const delay = Math.max(
      0,
      Date.parse(publishedAt) + USAGE_STALE_AFTER_MS + 1 - Date.now()
    );
    const timer = setTimeout(() => setNow(Date.now()), delay);
    return () => clearTimeout(timer);
  }, [scope, publishedAt]);
  const publicationExpired =
    !!publishedAt && now - Date.parse(publishedAt) > USAGE_STALE_AFTER_MS;
  return {
    data,
    coverage: data?.coverage ?? null,
    lastPublishedAt: data?.published_at ?? null,
    stale:
      !!data &&
      (data.status === "stale" || !!state.error || publicationExpired),
    unavailable:
      !data &&
      (!!error || snapshot?.status === "unavailable" || !context.canAdmin),
    activationBoundary: snapshot?.collection_start ?? null,
    activatedAt: snapshot?.activated_at ?? null,
    waiting: snapshot?.status === "waiting" && !error,
    isLoading: context.isLoading || capabilities.isLoading || state.isLoading,
    canAdmin: context.canAdmin,
    error,
    reload: async () => {
      await capabilities.mutate();
      await context.mutate();
      await state.mutate();
    },
  };
}
