import type {
  UsageGroup,
  UsageQuery,
  UsageSummary,
  UsageTotals,
} from "@/lib/orgmesh-enterprise/types";

interface UsageWireObject {
  group_by?: unknown;
  status?: unknown;
  activated_at?: unknown;
  collection_start?: unknown;
  coverage?: unknown;
  published_at?: unknown;
  revision?: unknown;
  groups?: unknown;
  cost_basis?: unknown;
  cost_notice?: unknown;
  value?: unknown;
  category?: unknown;
  incognito?: unknown;
  totals?: unknown;
  from?: unknown;
  to?: unknown;
  input_tokens?: unknown;
  output_tokens?: unknown;
  total_tokens?: unknown;
  cache_read_tokens?: unknown;
  cache_creation_tokens?: unknown;
  cost_cents?: unknown;
}

function isRecord(value: unknown): value is UsageWireObject {
  return typeof value === "object" && value !== null;
}
function isTimestamp(value: unknown): value is string {
  return (
    typeof value === "string" &&
    /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|\+00:00)$/.test(
      value
    ) &&
    Number.isFinite(Date.parse(value)) &&
    new Date(value).toISOString().slice(0, 10) === value.slice(0, 10)
  );
}
function isMidnight(value: unknown): value is string {
  return (
    isTimestamp(value) &&
    new Date(value).toISOString().endsWith("T00:00:00.000Z")
  );
}
function isInteger(value: unknown): value is string {
  return typeof value === "string" && /^(0|[1-9][0-9]{0,31})$/.test(value);
}
function isTotals(value: unknown): value is UsageTotals {
  return (
    isRecord(value) &&
    isInteger(value.input_tokens) &&
    isInteger(value.output_tokens) &&
    isInteger(value.total_tokens) &&
    isInteger(value.cache_read_tokens) &&
    isInteger(value.cache_creation_tokens) &&
    typeof value.cost_cents === "string" &&
    /^(0|[1-9][0-9]{0,31})\.[0-9]{6}$/.test(value.cost_cents) &&
    BigInt(value.total_tokens) ===
      BigInt(value.input_tokens) + BigInt(value.output_tokens)
  );
}
function isGroup(value: unknown): value is UsageGroup {
  return (
    isRecord(value) &&
    typeof value.value === "string" &&
    value.value.length > 0 &&
    Array.from(value.value).length <= 512 &&
    (value.category === "USER" ||
      value.category === "SYSTEM_ATTRIBUTED" ||
      value.category === "SYSTEM_UNATTRIBUTED") &&
    typeof value.incognito === "boolean" &&
    (value.category === "USER" || !value.incognito) &&
    isTotals(value.totals)
  );
}

/** Reject an incomplete or mismatched snapshot before it enters the private SWR cache. */
export function isUsageSummary(
  value: unknown,
  query: UsageQuery
): value is UsageSummary {
  if (
    !isRecord(value) ||
    value.group_by !== query.group_by ||
    !(
      value.status === "ready" ||
      value.status === "stale" ||
      value.status === "waiting" ||
      value.status === "unavailable"
    ) ||
    !Array.isArray(value.groups) ||
    value.groups.length > 1000 ||
    !value.groups.every(isGroup) ||
    !Number.isSafeInteger(value.revision) ||
    typeof value.revision !== "number" ||
    value.revision < 0 ||
    value.cost_basis !== "source_estimate_usd_cents" ||
    value.cost_notice !==
      "Source-estimated USD cents; 0 may mean missing pricing. Not settled charges." ||
    !(value.activated_at === null || isTimestamp(value.activated_at)) ||
    !(value.collection_start === null || isMidnight(value.collection_start)) ||
    !(value.published_at === null || isTimestamp(value.published_at))
  )
    return false;
  if (
    value.activated_at &&
    value.collection_start &&
    Date.parse(value.collection_start) !==
      Date.parse(`${value.activated_at.slice(0, 10)}T00:00:00Z`) + 86400000
  )
    return false;
  if (value.status === "waiting" || value.status === "unavailable") {
    return (
      value.coverage === null &&
      value.groups.length === 0 &&
      value.published_at === null
    );
  }
  const coverage = value.coverage;
  if (
    !isRecord(coverage) ||
    !isMidnight(coverage.from) ||
    !isMidnight(coverage.to) ||
    !value.activated_at ||
    !value.collection_start ||
    !value.published_at ||
    value.revision < 1 ||
    Date.parse(coverage.from) < Date.parse(query.start) ||
    Date.parse(coverage.from) < Date.parse(value.collection_start) ||
    Date.parse(coverage.to) !== Date.parse(query.end) ||
    Date.parse(coverage.from) >= Date.parse(coverage.to)
  )
    return false;
  const groups = new Set<string>();
  for (const group of value.groups) {
    const key = JSON.stringify([group.value, group.category, group.incognito]);
    if (groups.has(key)) return false;
    groups.add(key);
    if (value.group_by === "day") {
      const day = `${group.value}T00:00:00Z`;
      if (
        !/^\d{4}-\d{2}-\d{2}$/.test(group.value) ||
        !isMidnight(day) ||
        Date.parse(day) < Date.parse(coverage.from) ||
        Date.parse(day) >= Date.parse(coverage.to)
      )
        return false;
    }
  }
  return true;
}

/** Use BigInt and localized digit parts. Never round token or cents strings through Number. */
export function formatUsageInteger(value: string, locale: string): string {
  if (!isInteger(value)) throw new Error("Invalid usage integer");
  return new Intl.NumberFormat(locale).format(BigInt(value));
}
export function formatUsageCostCents(value: string, locale: string): string {
  if (!/^(0|[1-9][0-9]{0,31})\.[0-9]{6}$/.test(value))
    throw new Error("Invalid usage cost");
  const whole = value.slice(0, -7);
  const fraction = value.slice(-6);
  const digits = new Intl.NumberFormat(locale, { useGrouping: false });
  const decimal = new Intl.NumberFormat(locale, { minimumFractionDigits: 1 })
    .formatToParts(BigInt(0))
    .find((part) => part.type === "decimal")?.value;
  if (!decimal) throw new Error("Missing locale decimal separator");
  return `${formatUsageInteger(whole, locale)}${decimal}${Array.from(fraction)
    .map((digit) => digits.format(BigInt(digit)))
    .join("")}`;
}

export function defaultUsageDates(now = new Date()) {
  const today = new Date(`${now.toISOString().slice(0, 10)}T00:00:00Z`);
  return {
    start: new Date(today.getTime() - 29 * 86400000).toISOString().slice(0, 10),
    end: today.toISOString().slice(0, 10),
  };
}
export function usageDateBounds(now = new Date()) {
  const today = new Date(`${now.toISOString().slice(0, 10)}T00:00:00Z`);
  return {
    min: new Date(today.getTime() - 89 * 86400000).toISOString().slice(0, 10),
    max: today.toISOString().slice(0, 10),
  };
}

/** The visible end date is inclusive; the wire end is the following UTC midnight. */
export function usageDateQuery(
  startDate: string,
  endDate: string,
  groupBy: UsageQuery["group_by"],
  now = new Date()
): UsageQuery | undefined {
  const start = `${startDate}T00:00:00Z`;
  const end = `${endDate}T00:00:00Z`;
  const bounds = usageDateBounds(now);
  if (
    !/^\d{4}-\d{2}-\d{2}$/.test(startDate) ||
    !/^\d{4}-\d{2}-\d{2}$/.test(endDate) ||
    !isMidnight(start) ||
    !isMidnight(end) ||
    startDate < bounds.min ||
    endDate > bounds.max ||
    startDate > endDate
  )
    return undefined;
  return {
    start,
    end: new Date(Date.parse(end) + 86400000)
      .toISOString()
      .replace(".000Z", "Z"),
    group_by: groupBy,
  };
}
