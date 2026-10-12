"use client";

import useSWR from "swr";
import { usePathname } from "next/navigation";
import useCCPairs from "@/hooks/useCCPairs";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import { isAuthPath } from "@/lib/auth/paths";
import {
  ApplicationStatus,
  AppSettings,
  EnterpriseSettings,
  QueryHistoryType,
  Settings,
} from "@/lib/settings/types";
import { EE_ENABLED } from "@/lib/constants";
import { useOrgMeshBranding } from "@/lib/orgmesh-enterprise/hooks";
import { brandingLogoUrl } from "@/lib/orgmesh-enterprise/staticBranding";

const SETTINGS_ERROR_RETRY_INTERVAL = 5_000;

const DEFAULT_SETTINGS: Settings = {
  auto_scroll: true,
  application_status: ApplicationStatus.ACTIVE,
  gpu_enabled: false,
  maximum_chat_retention_days: null,
  notifications: [],
  needs_reindexing: false,
  anonymous_user_enabled: false,
  invite_only_enabled: false,
  deep_research_enabled: true,
  multi_model_chat_enabled: true,
  temperature_override_enabled: true,
  reasoning_override_enabled: true,
  query_history_type: QueryHistoryType.NORMAL,
};

/** Core failures remain fatal. Independent branding has a safe fallback. */
export function useSettings(): AppSettings {
  // Skip core settings on /auth/* routes: unauthenticated callers 403 there, and
  // the login shell only needs the independent public branding.
  const onAuthPath = isAuthPath(usePathname());

  const {
    data: rawSettings,
    error: settingsError,
    isLoading: settingsLoading,
  } = useSWR<Settings>(
    onAuthPath ? null : SWR_KEYS.settings,
    errorHandlingFetcher,
    {
      revalidateOnFocus: false,
      revalidateOnReconnect: false,
      revalidateIfStale: false,
      dedupingInterval: 30_000,
      errorRetryInterval: SETTINGS_ERROR_RETRY_INTERVAL,
    }
  );

  const core = rawSettings ?? DEFAULT_SETTINGS;
  const branding = useOrgMeshBranding();

  return {
    ...core,
    enterprise: null,
    appName: branding.data.name,
    greeting: branding.data.greeting,
    logoUrl: brandingLogoUrl(branding.data.logo_asset_id),
    vectorDbEnabled:
      !settingsLoading && !settingsError && core.vector_db_enabled !== false,
    isLoading: settingsLoading,
    error: settingsError,
  };
}

/**
 * Returns `true` when search mode is actually usable by the current user.
 *
 * This is a cross-cutting hook: it joins `useSettings()` (two settings
 * endpoints) with connector state (`useCCPairs`). It is intentionally kept
 * separate from `useSettings()` so that the connector list fetch only fires in
 * the small number of components that actually need it.
 */
export function useIsSearchModeAvailable(): boolean {
  const { vectorDbEnabled, search_ui_enabled } = useSettings();
  const { ccPairs } = useCCPairs(vectorDbEnabled);
  return search_ui_enabled !== false && ccPairs.length > 0;
}

/** Explicit legacy policy consumers opt in. Branding never enables this fetch. */
export function useEnterpriseSettings() {
  const { ee_features_enabled, isLoading, error } = useSettings();
  const isEnabled =
    EE_ENABLED || (!isLoading && !error && ee_features_enabled === true);
  const state = useSWR<EnterpriseSettings>(
    isEnabled ? SWR_KEYS.enterpriseSettings : null,
    errorHandlingFetcher,
    {
      revalidateOnFocus: false,
      errorRetryInterval: SETTINGS_ERROR_RETRY_INTERVAL,
    }
  );
  return { ...state, isEnabled, isLoading: isLoading || state.isLoading };
}
