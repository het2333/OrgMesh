import {
  CombinedSettings,
  EnterpriseSettings,
  ApplicationStatus,
  Settings,
  QueryHistoryType,
} from "@/lib/settings/types";
import { HOST_URL } from "@/lib/constants";
import { fetchSS } from "@/lib/utilsSS";
import { getWebVersion } from "@/lib/version";
import { fetchOrgMeshBrandingSS } from "@/lib/orgmesh-enterprise/svcSS";
import { brandingLogoUrl } from "@/lib/orgmesh-enterprise/staticBranding";

export async function fetchStandardSettingsSS(): Promise<Settings | null> {
  try {
    const response = await fetchSS("/settings");
    if (!response?.ok) return null;
    return response.json();
  } catch {
    return null;
  }
}

export async function fetchEnterpriseSettingsSS(): Promise<EnterpriseSettings | null> {
  try {
    const response = await fetchSS("/enterprise-settings");
    if (!response?.ok) return null;
    return response.json();
  } catch {
    return null;
  }
}

export async function fetchSettingsSS(): Promise<CombinedSettings | null> {
  const settingsTask = fetchSS("/settings");
  const brandingTask = fetchOrgMeshBrandingSS();

  try {
    const [settingsResponse, branding] = await Promise.all([
      settingsTask,
      brandingTask,
    ]);

    let settings: Settings;
    if (!settingsResponse) {
      throw new Error("Standard settings fetch failed.");
    }
    if (!settingsResponse.ok) {
      if (settingsResponse.status === 403 || settingsResponse.status === 401) {
        settings = {
          auto_scroll: true,
          application_status: ApplicationStatus.ACTIVE,
          gpu_enabled: false,
          maximum_chat_retention_days: null,
          notifications: [],
          needs_reindexing: false,
          anonymous_user_enabled: false,
          invite_only_enabled: false,
          deep_research_enabled: true,
          temperature_override_enabled: true,
          reasoning_override_enabled: true,
          query_history_type: QueryHistoryType.NORMAL,
        };
      } else {
        throw new Error(
          `fetchSettingsSS: settings failed status=${
            settingsResponse.status
          } body=${await settingsResponse.text()}`
        );
      }
    } else {
      settings = await settingsResponse.json();
    }

    if (settings.deep_research_enabled == null) {
      settings.deep_research_enabled = true;
    }

    return {
      settings,
      enterpriseSettings: null,
      customAnalyticsScript: null,
      webVersion: settings.version ?? getWebVersion(),
      webDomain: HOST_URL,
      appName: branding.name,
      logoUrl: brandingLogoUrl(branding.logo_asset_id),
      greeting: branding.greeting,
    };
  } catch (error) {
    console.error("fetchSettingsSS exception: ", error);
    return null;
  }
}
