import type {
  AuditPage,
  AuditQuery,
  BrandingPatch,
  BrandingView,
  EnterpriseCapabilities,
  EnterpriseContext,
  UsageQuery,
  UsageSummary,
} from "@/lib/orgmesh-enterprise/types";
import {
  readBrandingResponse,
  isAuditPage,
} from "@/lib/orgmesh-enterprise/staticBranding";

import { isUsageSummary } from "@/lib/orgmesh-enterprise/usage";

export const ENTERPRISE_API = "/api/orgmesh-enterprise/v1";
export const PRIVATE_CACHE_PREFIX = "orgmesh-enterprise-private";

export class EnterpriseApiError extends Error {
  constructor(public readonly status: number) {
    super(`OrgMesh request failed (${status})`);
  }
}

function successfulResponse(response: Response): Response {
  if (!response.ok) throw new EnterpriseApiError(response.status);
  return response;
}

export async function fetchOrgMeshBranding(): Promise<BrandingView> {
  return readBrandingResponse(
    successfulResponse(
      await fetch(`${ENTERPRISE_API}/branding`, {
        cache: "no-store",
        credentials: "include",
      })
    )
  );
}

export async function patchOrgMeshBranding(
  patch: BrandingPatch,
  key: string
): Promise<BrandingView> {
  return readBrandingResponse(
    successfulResponse(
      await fetch(`${ENTERPRISE_API}/branding`, {
        method: "PATCH",
        credentials: "include",
        cache: "no-store",
        headers: { "Content-Type": "application/json", "Idempotency-Key": key },
        body: JSON.stringify(patch),
      })
    )
  );
}

export async function fetchEnterpriseCapabilities(): Promise<EnterpriseCapabilities> {
  const response = await fetch(`${ENTERPRISE_API}/capabilities`, {
    cache: "no-store",
    credentials: "include",
  });
  if (!response.ok) throw new EnterpriseApiError(response.status);
  return response.json();
}

export async function fetchEnterpriseContext(): Promise<EnterpriseContext> {
  const response = successfulResponse(
    await fetch(`${ENTERPRISE_API}/context`, {
      cache: "no-store",
      credentials: "include",
    })
  );
  const data: unknown = await response.json();
  if (
    typeof data !== "object" ||
    data === null ||
    !("user_id" in data) ||
    typeof data.user_id !== "string" ||
    !data.user_id ||
    !("tenant_id" in data) ||
    typeof data.tenant_id !== "string" ||
    !data.tenant_id
  ) {
    throw new Error("Invalid organization context");
  }
  return { user_id: data.user_id, tenant_id: data.tenant_id };
}

export async function fetchEnterpriseAudit(
  query: AuditQuery
): Promise<AuditPage> {
  const params = new URLSearchParams({
    start: query.start,
    end: query.end,
    limit: String(query.limit ?? 50),
    cursor: query.cursor ?? "",
    action: query.action ?? "",
    result: query.result ?? "",
  });
  const response = await fetch(`${ENTERPRISE_API}/audit/events?${params}`, {
    cache: "no-store",
    credentials: "include",
  });
  if (!response.ok) throw new EnterpriseApiError(response.status);
  const page: unknown = await response.json();
  if (!isAuditPage(page)) throw new Error("Invalid audit response");
  return page;
}

export type EnterprisePrivateCacheKey = readonly [
  typeof PRIVATE_CACHE_PREFIX,
  "context" | "audit" | "usage",
  string,
  ...unknown[],
];

export function isEnterprisePrivateKey(
  key: unknown
): key is EnterprisePrivateCacheKey {
  return (
    Array.isArray(key) &&
    key[0] === PRIVATE_CACHE_PREFIX &&
    (key[1] === "context" || key[1] === "audit" || key[1] === "usage") &&
    typeof key[2] === "string"
  );
}

export async function fetchEnterpriseUsage(
  query: UsageQuery
): Promise<UsageSummary> {
  const params = new URLSearchParams({
    start: query.start,
    end: query.end,
    group_by: query.group_by,
  });
  const response = successfulResponse(
    await fetch(`${ENTERPRISE_API}/usage/summary?${params}`, {
      cache: "no-store",
      credentials: "include",
    })
  );
  const summary: unknown = await response.json();
  if (!isUsageSummary(summary, query))
    throw new Error("Invalid usage response");
  return summary;
}
