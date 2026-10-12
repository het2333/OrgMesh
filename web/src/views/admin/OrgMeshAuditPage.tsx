"use client";

import { useState } from "react";
import { useFormatter, useTranslations } from "next-intl";
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
import { SvgHistory } from "@opal/icons";
import {
  useEnterpriseAudit,
  useEnterpriseCapabilities,
} from "@/lib/orgmesh-enterprise/hooks";
import type { AuditQuery } from "@/lib/orgmesh-enterprise/types";

function defaultRange() {
  const end = new Date();
  const start = new Date(end.getTime() - 30 * 24 * 60 * 60 * 1000);
  return {
    start: start.toISOString().slice(0, -1),
    end: end.toISOString().slice(0, -1),
  };
}

export default function OrgMeshAuditPage() {
  const t = useTranslations("orgmeshEnterprise");
  const formatter = useFormatter();
  const [range, setRange] = useState(defaultRange);
  const [action, setAction] = useState<AuditQuery["action"]>("");
  const [result, setResult] = useState<AuditQuery["result"]>("");
  const [invalidRange, setInvalidRange] = useState(false);
  const [query, setQuery] = useState<AuditQuery>(() => ({
    start: `${range.start}Z`,
    end: `${range.end}Z`,
    limit: 50,
  }));
  const state = useEnterpriseAudit(query);
  const capabilities = useEnterpriseCapabilities();

  function apply() {
    const start = new Date(`${range.start}Z`);
    const end = new Date(`${range.end}Z`);
    const duration = end.getTime() - start.getTime();
    if (
      !Number.isFinite(duration) ||
      duration <= 0 ||
      duration > 90 * 24 * 60 * 60 * 1000
    ) {
      setInvalidRange(true);
      return;
    }
    setInvalidRange(false);
    setQuery({
      start: start.toISOString(),
      end: end.toISOString(),
      limit: 50,
      action,
      result,
    });
  }

  function fieldLabel(field: string) {
    return field === "name"
      ? t("audit.fieldName")
      : field === "greeting"
        ? t("audit.fieldGreeting")
        : t("audit.fieldLogo");
  }

  return (
    <SettingsLayouts.Root width="lg">
      <SettingsLayouts.Header
        icon={SvgHistory}
        title={t("audit.title")}
        description={t("audit.description")}
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
        ) : capabilities.data?.audit_enabled === false ? (
          <IllustrationContent title={t("common.disabled")} />
        ) : (
          <>
            <form
              onSubmit={(event) => {
                event.preventDefault();
                apply();
              }}
              className="grid grid-cols-1 sm:grid-cols-2 gap-3 min-w-0"
            >
              <InputVertical title={t("audit.start")}>
                <InputTypeIn
                  aria-label={t("audit.start")}
                  type="datetime-local"
                  step="0.001"
                  value={range.start}
                  onChange={(event) =>
                    setRange({ ...range, start: event.target.value })
                  }
                />
              </InputVertical>
              <InputVertical title={t("audit.end")}>
                <InputTypeIn
                  aria-label={t("audit.end")}
                  type="datetime-local"
                  step="0.001"
                  value={range.end}
                  onChange={(event) =>
                    setRange({ ...range, end: event.target.value })
                  }
                />
              </InputVertical>
              <InputVertical title={t("audit.action")}>
                <InputSingleSelect
                  value={action || "all"}
                  onValueChange={(value) =>
                    setAction(
                      value === "branding.created" ||
                        value === "branding.updated"
                        ? value
                        : ""
                    )
                  }
                >
                  <InputSingleSelect.Trigger aria-label={t("audit.action")} />
                  <InputSingleSelect.Content>
                    <InputSingleSelect.Item value="all">
                      {t("audit.allActions")}
                    </InputSingleSelect.Item>
                    <InputSingleSelect.Item value="branding.created">
                      {t("audit.created")}
                    </InputSingleSelect.Item>
                    <InputSingleSelect.Item value="branding.updated">
                      {t("audit.updated")}
                    </InputSingleSelect.Item>
                  </InputSingleSelect.Content>
                </InputSingleSelect>
              </InputVertical>
              <InputVertical title={t("audit.result")}>
                <InputSingleSelect
                  value={result || "all"}
                  onValueChange={(value) =>
                    setResult(value === "success" ? value : "")
                  }
                >
                  <InputSingleSelect.Trigger aria-label={t("audit.result")} />
                  <InputSingleSelect.Content>
                    <InputSingleSelect.Item value="all">
                      {t("audit.allResults")}
                    </InputSingleSelect.Item>
                    <InputSingleSelect.Item value="success">
                      {t("audit.success")}
                    </InputSingleSelect.Item>
                  </InputSingleSelect.Content>
                </InputSingleSelect>
              </InputVertical>
              <Button type="submit">{t("audit.apply")}</Button>
            </form>
            {invalidRange && (
              <Text as="p" role="alert" color="status-error-05">
                {t("audit.rangeError")}
              </Text>
            )}
            {state.isLoading ? (
              <div role="status">
                <IconLoader />
                <Text>{t("common.loading")}</Text>
              </div>
            ) : state.error || capabilities.error ? (
              <div role="alert">
                <IllustrationContent title={t("common.unavailable")} />
                <Button
                  onClick={() => {
                    void state.reload();
                    void capabilities.mutate();
                  }}
                >
                  {t("common.reload")}
                </Button>
              </div>
            ) : state.data?.events.length === 0 ? (
              <IllustrationContent title={t("audit.empty")} />
            ) : (
              <ul aria-label={t("audit.title")} className="flex flex-col gap-3">
                {state.data?.events.map((event) => (
                  <li
                    key={event.event_id}
                    className="rounded-lg border border-border-01 p-3 flex flex-col gap-1 min-w-0"
                  >
                    <Text font="main-ui-action">
                      {event.action === "branding.created"
                        ? t("audit.created")
                        : t("audit.updated")}
                    </Text>
                    <Text font="secondary-body">
                      {formatter.dateTime(new Date(event.created_at), {
                        dateStyle: "medium",
                        timeStyle: "short",
                        timeZone: "UTC",
                      })}
                    </Text>
                    <Text wordWrap="wrap-anywhere">
                      {t("audit.actorKind", { id: event.user_id })}
                    </Text>
                    <Text>{t("audit.resourceName")}</Text>
                    <Text>{t("audit.success")}</Text>
                    <Text>
                      {t("audit.versions", {
                        before: event.before_version,
                        after: event.after_version,
                      })}
                    </Text>
                    <Text>
                      {t("audit.fields", {
                        fields: formatter.list(
                          event.changed_fields.map(fieldLabel)
                        ),
                      })}
                    </Text>
                    <Text font="secondary-mono" wordWrap="wrap-anywhere">
                      {t("audit.request", { id: event.request_id })}
                    </Text>
                  </li>
                ))}
              </ul>
            )}
            <div className="flex flex-wrap gap-2">
              <Button
                prominence="secondary"
                disabled={!query.cursor || state.isLoading}
                onClick={() => setQuery({ ...query, cursor: "" })}
              >
                {t("audit.first")}
              </Button>
              <Button
                prominence="secondary"
                disabled={!state.data?.next_cursor || state.isLoading}
                onClick={() => {
                  if (state.data?.next_cursor)
                    setQuery({ ...query, cursor: state.data.next_cursor });
                }}
              >
                {t("audit.next")}
              </Button>
            </div>
          </>
        )}
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
