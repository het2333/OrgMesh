import type { BrandingView, LogoAssetId } from "@/lib/orgmesh-enterprise/types";

export const STATIC_BRANDING: BrandingView = {
  name: "OrgMesh",
  greeting: "",
  logo_asset_id: "orgmesh-default",
  version: 0,
  source: "static",
};

const REVIEWED_LOGOS = {
  "orgmesh-default": "/orgmesh.svg",
} satisfies Record<LogoAssetId, string>;

export function brandingLogoUrl(assetId: LogoAssetId): string {
  return REVIEWED_LOGOS[assetId];
}

export function isPlainBrandText(value: string, maximum: number): boolean {
  return (
    [...value].length <= maximum &&
    !/[<>\p{Cc}]/u.test(value.replace(/[\n\t]/g, ""))
  );
}

export function isBrandingView(value: unknown): value is BrandingView {
  if (
    typeof value !== "object" ||
    value === null ||
    !("name" in value) ||
    typeof value.name !== "string" ||
    [...value.name].length < 1 ||
    !isPlainBrandText(value.name, 50) ||
    !("greeting" in value) ||
    typeof value.greeting !== "string" ||
    !isPlainBrandText(value.greeting, 120) ||
    !("logo_asset_id" in value) ||
    value.logo_asset_id !== "orgmesh-default" ||
    !("version" in value) ||
    typeof value.version !== "number" ||
    !Number.isSafeInteger(value.version) ||
    value.version < 0 ||
    !("source" in value) ||
    !(
      (value.source === "static" && value.version === 0) ||
      (value.source === "dynamic" && value.version > 0)
    )
  ) {
    return false;
  }
  return true;
}

/** Decode only reviewed plain-text fields at the HTTP boundary. */
export async function readBrandingResponse(
  response: Response
): Promise<BrandingView> {
  const value: unknown = await response.json();
  if (!isBrandingView(value)) throw new Error("Invalid branding response");
  return value;
}

import type { AuditEvent, AuditPage } from "@/lib/orgmesh-enterprise/types";

const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function isAuditEvent(value: unknown): value is AuditEvent {
  return (
    typeof value === "object" &&
    value !== null &&
    "event_id" in value &&
    typeof value.event_id === "string" &&
    UUID_PATTERN.test(value.event_id) &&
    "user_id" in value &&
    typeof value.user_id === "string" &&
    UUID_PATTERN.test(value.user_id) &&
    "request_id" in value &&
    typeof value.request_id === "string" &&
    UUID_PATTERN.test(value.request_id) &&
    "created_at" in value &&
    typeof value.created_at === "string" &&
    Number.isFinite(Date.parse(value.created_at)) &&
    /(Z|[+-]\d{2}:\d{2})$/.test(value.created_at) &&
    "actor_kind" in value &&
    value.actor_kind === "user" &&
    "resource_id" in value &&
    value.resource_id === "branding-config" &&
    "result" in value &&
    value.result === "success" &&
    "before_version" in value &&
    typeof value.before_version === "number" &&
    Number.isSafeInteger(value.before_version) &&
    value.before_version >= 0 &&
    "after_version" in value &&
    typeof value.after_version === "number" &&
    Number.isSafeInteger(value.after_version) &&
    value.after_version === value.before_version + 1 &&
    "action" in value &&
    ((value.action === "branding.created" && value.before_version === 0) ||
      (value.action === "branding.updated" && value.before_version > 0)) &&
    "changed_fields" in value &&
    Array.isArray(value.changed_fields) &&
    value.changed_fields.length > 0 &&
    value.changed_fields.length <= 3 &&
    new Set(value.changed_fields).size === value.changed_fields.length &&
    value.changed_fields.every(
      (field) =>
        field === "name" || field === "greeting" || field === "logo_asset_id"
    )
  );
}

export function isAuditPage(value: unknown): value is AuditPage {
  return (
    typeof value === "object" &&
    value !== null &&
    "events" in value &&
    Array.isArray(value.events) &&
    value.events.length <= 100 &&
    value.events.every(isAuditEvent) &&
    "next_cursor" in value &&
    (value.next_cursor === null ||
      (typeof value.next_cursor === "string" &&
        value.next_cursor.length <= 512))
  );
}
