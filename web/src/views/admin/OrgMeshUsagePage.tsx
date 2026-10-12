"use client";

import { useEffect, useState } from "react";
import { useFormatter, useLocale, useTranslations } from "next-intl";
import {
  Button,
  IconLoader,
  InputSingleSelect,
  InputTypeIn,
  Text,
} from "@opal/components";
import {
  IllustrationContent,
  InputVertical,
  SettingsLayouts,
} from "@opal/layouts";
import { SvgPieChart } from "@opal/icons";
import {
  useEnterpriseCapabilities,
  useEnterpriseUsage,
} from "@/lib/orgmesh-enterprise/hooks";
import type {
  UsageGroup,
  UsageGroupBy,
  UsageQuery,
} from "@/lib/orgmesh-enterprise/types";
import {
  defaultUsageDates,
  formatUsageCostCents,
  formatUsageInteger,
  usageDateBounds,
  usageDateQuery,
} from "@/lib/orgmesh-enterprise/usage";

export default function OrgMeshUsagePage() {
  const t = useTranslations("orgmeshEnterprise");
  const locale = useLocale();
  const formatter = useFormatter();
  const [range, setRange] = useState(defaultUsageDates);
  const [hasCustomRange, setHasCustomRange] = useState(false);
  const [groupBy, setGroupBy] = useState<UsageGroupBy>("day");
  const [invalidRange, setInvalidRange] = useState(false);
  const [query, setQuery] = useState<UsageQuery>(() => ({
    start: `${range.start}T00:00:00Z`,
    end: new Date(Date.parse(`${range.end}T00:00:00Z`) + 86400000)
      .toISOString()
      .replace(".000Z", "Z"),
    group_by: "day",
  }));
  const state = useEnterpriseUsage(query);
  const capabilities = useEnterpriseCapabilities();
  const bounds = usageDateBounds();

  // Keep the untouched default window current without replacing the user's dates.
  useEffect(() => {
    if (
      hasCustomRange ||
      !state.canAdmin ||
      capabilities.error ||
      !capabilities.data?.usage_enabled
    )
      return;
    const nextMidnight = Date.parse(`${range.end}T00:00:00Z`) + 86400000;
    const timer = setTimeout(
      () => {
        const nextRange = defaultUsageDates();
        setRange(nextRange);
        setQuery(
          (current) =>
            usageDateQuery(nextRange.start, nextRange.end, current.group_by) ??
            current
        );
      },
      Math.max(0, nextMidnight - Date.now())
    );
    return () => clearTimeout(timer);
  }, [
    hasCustomRange,
    range.end,
    state.canAdmin,
    capabilities.error,
    capabilities.data?.usage_enabled,
  ]);

  function apply() {
    const nextQuery = usageDateQuery(range.start, range.end, groupBy);
    setInvalidRange(!nextQuery);
    if (nextQuery) setQuery(nextQuery);
  }
  function timestamp(value: string) {
    return formatter.dateTime(new Date(value), {
      dateStyle: "medium",
      timeStyle: "short",
      timeZone: "UTC",
    });
  }
  function category(group: UsageGroup) {
    if (group.category === "SYSTEM_ATTRIBUTED")
      return t("usage.systemAttributed");
    if (group.category === "SYSTEM_UNATTRIBUTED")
      return t("usage.systemUnattributed");
    return group.incognito ? t("usage.incognitoUser") : t("usage.user");
  }

  return (
    <SettingsLayouts.Root width="lg">
      <SettingsLayouts.Header
        icon={SvgPieChart}
        title={t("usage.title")}
        description={t("usage.description")}
        backButton
      />
      <SettingsLayouts.Body>
        {!state.canAdmin ? (
          <div role="alert">
            <IllustrationContent title={t("common.accessRequired")} />
          </div>
        ) : capabilities.isLoading ? (
          <div role="status">
            <IconLoader />
            <Text>{t("common.loading")}</Text>
          </div>
        ) : capabilities.error || !capabilities.data ? (
          <div role="alert">
            <IllustrationContent title={t("common.unavailable")} />
            <Button onClick={() => void state.reload()}>
              {t("common.reload")}
            </Button>
          </div>
        ) : !capabilities.data.usage_enabled ? (
          <IllustrationContent title={t("usage.disabled")} />
        ) : (
          <>
            <form
              noValidate
              onSubmit={(event) => {
                event.preventDefault();
                apply();
              }}
              className="grid grid-cols-1 sm:grid-cols-2 gap-3 min-w-0"
            >
              <InputVertical title={t("usage.start")}>
                <InputTypeIn
                  type="date"
                  aria-label={t("usage.start")}
                  min={bounds.min}
                  max={bounds.max}
                  value={range.start}
                  onChange={(event) => {
                    setHasCustomRange(true);
                    setRange({ ...range, start: event.target.value });
                  }}
                />
              </InputVertical>
              <InputVertical title={t("usage.end")}>
                <InputTypeIn
                  type="date"
                  aria-label={t("usage.end")}
                  min={bounds.min}
                  max={bounds.max}
                  value={range.end}
                  onChange={(event) => {
                    setHasCustomRange(true);
                    setRange({ ...range, end: event.target.value });
                  }}
                />
              </InputVertical>
              <InputVertical title={t("usage.groupBy")}>
                <InputSingleSelect
                  value={groupBy}
                  onValueChange={(value) => {
                    if (
                      value === "day" ||
                      value === "model" ||
                      value === "flow"
                    )
                      setGroupBy(value);
                  }}
                >
                  <InputSingleSelect.Trigger aria-label={t("usage.groupBy")} />
                  <InputSingleSelect.Content>
                    <InputSingleSelect.Item value="day">
                      {t("usage.day")}
                    </InputSingleSelect.Item>
                    <InputSingleSelect.Item value="model">
                      {t("usage.model")}
                    </InputSingleSelect.Item>
                    <InputSingleSelect.Item value="flow">
                      {t("usage.flow")}
                    </InputSingleSelect.Item>
                  </InputSingleSelect.Content>
                </InputSingleSelect>
              </InputVertical>
              <div className="flex flex-wrap items-end gap-2">
                <Button type="submit" disabled={state.isLoading}>
                  {t("usage.apply")}
                </Button>
                <Button
                  prominence="secondary"
                  disabled={state.isLoading}
                  onClick={() => void state.reload()}
                >
                  {t("common.reload")}
                </Button>
              </div>
            </form>
            {invalidRange && (
              <Text as="p" role="alert" color="status-error-05">
                {t("usage.rangeError")}
              </Text>
            )}
            <Text as="p" font="secondary-body">
              {t("usage.intraday")}
            </Text>
            <Text as="p" font="secondary-body">
              {t("usage.pricingNotice")}
            </Text>
            <Text as="p" font="secondary-body">
              {t("usage.categoryNotice")}
            </Text>
            {state.activatedAt && (
              <Text as="p">
                {t("usage.activatedAt", { time: timestamp(state.activatedAt) })}
              </Text>
            )}
            {state.activationBoundary && (
              <Text as="p">
                {t("usage.collectionStart", {
                  time: timestamp(state.activationBoundary),
                })}
              </Text>
            )}
            {state.coverage && (
              <Text as="p">
                {t("usage.coverage", {
                  start: timestamp(state.coverage.from),
                  end: timestamp(state.coverage.to),
                })}
              </Text>
            )}
            {state.lastPublishedAt && (
              <Text as="p">
                {t("usage.publishedAt", {
                  time: timestamp(state.lastPublishedAt),
                })}
              </Text>
            )}
            {state.stale && state.lastPublishedAt && (
              <Text as="p" role="status">
                {t("usage.stale", {
                  time: timestamp(state.lastPublishedAt),
                })}
              </Text>
            )}
            {state.isLoading && !state.data ? (
              <div role="status">
                <IconLoader />
                <Text>{t("common.loading")}</Text>
              </div>
            ) : state.unavailable ? (
              <div role="alert">
                <IllustrationContent title={t("usage.unavailable")} />
              </div>
            ) : state.waiting ? (
              <IllustrationContent title={t("usage.waiting")} />
            ) : state.data?.groups.length === 0 ? (
              <IllustrationContent title={t("usage.empty")} />
            ) : state.data ? (
              <ul
                aria-label={t("usage.groups")}
                className="flex flex-col gap-3"
              >
                {state.data.groups.map((group) => (
                  <li
                    key={JSON.stringify([
                      group.value,
                      group.category,
                      group.incognito,
                    ])}
                    className="rounded-lg border border-border-01 p-3 flex flex-col gap-1 min-w-0"
                  >
                    <Text
                      as="h2"
                      font="main-ui-action"
                      wordWrap="wrap-anywhere"
                    >
                      {query.group_by === "day"
                        ? formatter.dateTime(
                            new Date(`${group.value}T00:00:00Z`),
                            { dateStyle: "medium", timeZone: "UTC" }
                          )
                        : group.value}
                    </Text>
                    <Text>{category(group)}</Text>
                    <Text>
                      {t("usage.inputTokens", {
                        value: formatUsageInteger(
                          group.totals.input_tokens,
                          locale
                        ),
                      })}
                    </Text>
                    <Text>
                      {t("usage.outputTokens", {
                        value: formatUsageInteger(
                          group.totals.output_tokens,
                          locale
                        ),
                      })}
                    </Text>
                    <Text>
                      {t("usage.totalTokens", {
                        value: formatUsageInteger(
                          group.totals.total_tokens,
                          locale
                        ),
                      })}
                    </Text>
                    <Text>
                      {t("usage.cacheReadTokens", {
                        value: formatUsageInteger(
                          group.totals.cache_read_tokens,
                          locale
                        ),
                      })}
                    </Text>
                    <Text>
                      {t("usage.cacheCreationTokens", {
                        value: formatUsageInteger(
                          group.totals.cache_creation_tokens,
                          locale
                        ),
                      })}
                    </Text>
                    <Text>
                      {t("usage.cost", {
                        value: formatUsageCostCents(
                          group.totals.cost_cents,
                          locale
                        ),
                      })}
                    </Text>
                  </li>
                ))}
              </ul>
            ) : null}
          </>
        )}
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
