import { fetchSS } from "@/lib/utilsSS";
import {
  readBrandingResponse,
  STATIC_BRANDING,
} from "@/lib/orgmesh-enterprise/staticBranding";
import type { BrandingView } from "@/lib/orgmesh-enterprise/types";

export async function fetchOrgMeshBrandingSS(): Promise<BrandingView> {
  try {
    const response = await fetchSS("/orgmesh-enterprise/v1/branding", {
      cache: "no-store",
    });
    if (response.ok) return await readBrandingResponse(response);
  } catch {
    // Public branding does not make core settings unavailable.
  }
  return STATIC_BRANDING;
}
