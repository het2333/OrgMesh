import type { Metadata } from "next";
import { fetchOrgMeshBrandingSS } from "@/lib/orgmesh-enterprise/svcSS";
import { brandingLogoUrl } from "@/lib/orgmesh-enterprise/staticBranding";

/** Server-side twin of the independent display name. */
export async function fetchAppName(): Promise<string> {
  return (await fetchOrgMeshBrandingSS()).name;
}

export async function generateFaviconMetadata(): Promise<Metadata["icons"]> {
  return {
    icon: brandingLogoUrl((await fetchOrgMeshBrandingSS()).logo_asset_id),
  };
}

export async function generateAdminTitleMetadata(): Promise<Metadata["title"]> {
  return `Admin — ${await fetchAppName()}`;
}
