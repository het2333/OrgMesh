export type LogoAssetId = "orgmesh-default";
export interface BrandingFields {
  name: string;
  greeting: string;
  logo_asset_id: LogoAssetId;
}
export interface BrandingView extends BrandingFields {
  version: number;
  source: "static" | "dynamic";
}
export interface BrandingPatch extends BrandingFields {
  expected_version: number;
}
export interface EnterpriseCapabilities {
  branding_enabled: boolean;
  audit_enabled: boolean;
  usage_enabled: boolean;
  static_branding_version: number;
}
export interface EnterpriseContext {
  user_id: string;
  tenant_id: string;
}
export interface AuditQuery {
  start: string;
  end: string;
  limit?: number;
  cursor?: string;
  action?: "" | "branding.created" | "branding.updated";
  result?: "" | "success";
}
export interface AuditEvent {
  event_id: string;
  created_at: string;
  user_id: string;
  actor_kind: "user";
  resource_id: "branding-config";
  action: "branding.created" | "branding.updated";
  result: "success";
  before_version: number;
  after_version: number;
  changed_fields: (keyof BrandingFields)[];
  request_id: string;
}
export interface AuditPage {
  events: AuditEvent[];
  next_cursor: string | null;
}

export type UsageGroupBy = "day" | "model" | "flow";
export interface UsageQuery {
  start: string;
  end: string;
  group_by: UsageGroupBy;
}
export interface UsageCoverage {
  from: string;
  to: string;
}
export interface UsageTotals {
  input_tokens: string;
  output_tokens: string;
  total_tokens: string;
  cache_read_tokens: string;
  cache_creation_tokens: string;
  cost_cents: string;
}
export interface UsageGroup {
  value: string;
  category: "USER" | "SYSTEM_ATTRIBUTED" | "SYSTEM_UNATTRIBUTED";
  incognito: boolean;
  totals: UsageTotals;
}
export interface UsageSummary {
  group_by: UsageGroupBy;
  status: "ready" | "stale" | "waiting" | "unavailable";
  activated_at: string | null;
  collection_start: string | null;
  coverage: UsageCoverage | null;
  published_at: string | null;
  revision: number;
  groups: UsageGroup[];
  cost_basis: "source_estimate_usd_cents";
  cost_notice: "Source-estimated USD cents; 0 may mean missing pricing. Not settled charges.";
}
