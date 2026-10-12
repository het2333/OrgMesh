"use client";

import { useRef, useState } from "react";
import { useTranslations } from "next-intl";
import {
  Button,
  IconLoader,
  InputTextArea,
  InputTypeIn,
  Text,
} from "@opal/components";
import {
  IllustrationContent,
  InputVertical,
  SettingsLayouts,
} from "@opal/layouts";
import { SvgPaintBrush } from "@opal/icons";
import {
  useEnterpriseCapabilities,
  useEnterpriseContext,
  useOrgMeshBranding,
  type BrandingState,
} from "@/lib/orgmesh-enterprise/hooks";
import {
  EnterpriseApiError,
  patchOrgMeshBranding,
} from "@/lib/orgmesh-enterprise/svc";
import {
  brandingLogoUrl,
  isPlainBrandText,
} from "@/lib/orgmesh-enterprise/staticBranding";
import type {
  BrandingPatch,
  BrandingView,
  EnterpriseContext,
} from "@/lib/orgmesh-enterprise/types";

interface BrandingFormProps {
  branding: BrandingState;
  context: EnterpriseContext;
  enabled: boolean;
}

function BrandingForm({ branding, context, enabled }: BrandingFormProps) {
  const t = useTranslations("orgmeshEnterprise");
  const [base, setBase] = useState(branding.data);
  const [name, setName] = useState(base.name);
  const [greeting, setGreeting] = useState(base.greeting);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<
    | "conflict"
    | "unavailable"
    | "validation"
    | "saved"
    | "authInterrupted"
    | "failed"
    | null
  >(null);
  const submitting = useRef(false);
  const attempt = useRef<{ payload: string; key: string } | null>(null);
  const currentContext = useEnterpriseContext();
  const scopeValid =
    currentContext.data?.user_id === context.user_id &&
    currentContext.data?.tenant_id === context.tenant_id;
  const dirty = name !== base.name || greeting !== base.greeting;
  const readOnly = !enabled || !!branding.error || !scopeValid;

  function reset(data: BrandingView) {
    setBase(data);
    setName(data.name);
    setGreeting(data.greeting);
    setNotice(null);
    attempt.current = null;
  }

  async function reload() {
    if (submitting.current) return;
    try {
      if (currentContext.error) {
        await currentContext.mutate();
        setNotice(null);
        return;
      }
      const latest = await branding.reload();
      if (latest) reset(latest);
    } catch {
      setNotice("unavailable");
    }
  }

  async function save() {
    if (submitting.current || readOnly || !dirty || notice === "conflict")
      return;
    if (
      ![...name].length ||
      !isPlainBrandText(name, 50) ||
      !isPlainBrandText(greeting, 120)
    ) {
      setNotice("validation");
      return;
    }
    if (!scopeValid) {
      setNotice("authInterrupted");
      return;
    }
    const patch: BrandingPatch = {
      name,
      greeting,
      logo_asset_id: base.logo_asset_id,
      expected_version: base.version,
    };
    const payload = JSON.stringify(patch);
    if (attempt.current?.payload !== payload)
      attempt.current = { payload, key: crypto.randomUUID() };
    const key = attempt.current.key;
    submitting.current = true;
    setSaving(true);
    setNotice(null);
    try {
      const result = await patchOrgMeshBranding(patch, key);
      await branding.reload(result, { revalidate: false });
      reset(result);
      setNotice("saved");
    } catch (error) {
      setNotice(
        error instanceof EnterpriseApiError
          ? error.status === 409
            ? "conflict"
            : error.status === 401 || error.status === 403
              ? "authInterrupted"
              : error.status === 503
                ? "unavailable"
                : "failed"
          : "unavailable"
      );
    } finally {
      submitting.current = false;
      setSaving(false);
    }
  }

  const message =
    notice === "conflict"
      ? t("branding.conflict")
      : notice === "unavailable"
        ? t("branding.unavailable")
        : notice === "validation"
          ? t("branding.validation")
          : notice === "saved"
            ? t("branding.saved")
            : notice === "authInterrupted"
              ? t("common.authInterrupted")
              : notice === "failed"
                ? t("common.failed")
                : null;

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        void save();
      }}
      className="flex flex-col gap-4 min-w-0"
    >
      <div className="flex flex-wrap gap-2">
        <Text font="secondary-body">
          {t("branding.version", { version: base.version })}
        </Text>
        <Text font="secondary-body" color="text-03">
          {base.source === "static"
            ? t("branding.static")
            : t("branding.dynamic")}
        </Text>
      </div>
      {!enabled && <Text as="p">{t("common.disabled")}</Text>}
      {currentContext.error && (
        <Text as="p" role="alert" color="status-error-05">
          {t("common.unavailable")}
        </Text>
      )}
      {branding.error && (
        <Text as="p" role="alert" color="status-error-05">
          {t("branding.unavailable")}
        </Text>
      )}
      <InputVertical
        title={t("branding.name.label")}
        description={t("branding.name.help")}
      >
        <InputTypeIn
          aria-label={t("branding.name.label")}
          value={name}
          onChange={(event) => {
            setName(event.target.value);
            if (notice !== "conflict") setNotice(null);
          }}
          variant={readOnly || saving ? "disabled" : "primary"}
        />
      </InputVertical>
      <InputVertical
        title={t("branding.greeting.label")}
        description={t("branding.greeting.help")}
      >
        <InputTextArea
          aria-label={t("branding.greeting.label")}
          value={greeting}
          onChange={(event) => {
            setGreeting(event.target.value);
            if (notice !== "conflict") setNotice(null);
          }}
          variant={readOnly || saving ? "disabled" : "primary"}
        />
      </InputVertical>
      <InputVertical
        title={t("branding.logo.label")}
        description={t("branding.logo.description")}
      >
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={brandingLogoUrl(base.logo_asset_id)}
          alt={t("branding.logo.description")}
          width={48}
          height={48}
        />
      </InputVertical>
      {message && (
        <Text
          as="p"
          role={notice === "saved" ? "status" : "alert"}
          color={notice === "saved" ? "status-success-05" : "status-error-05"}
        >
          {message}
        </Text>
      )}
      <div className="flex flex-wrap gap-2">
        <Button
          type="submit"
          disabled={saving || readOnly || !dirty || notice === "conflict"}
        >
          {t("common.save")}
        </Button>
        <Button
          prominence="secondary"
          disabled={saving || !dirty}
          onClick={() => reset(base)}
        >
          {t("common.cancel")}
        </Button>
        <Button
          prominence="tertiary"
          disabled={saving}
          onClick={() => void reload()}
        >
          {t("common.reload")}
        </Button>
        {saving && <IconLoader />}
      </div>
    </form>
  );
}

export default function OrgMeshBrandingPage() {
  const t = useTranslations("orgmeshEnterprise");
  const branding = useOrgMeshBranding();
  const capabilities = useEnterpriseCapabilities();
  const context = useEnterpriseContext();
  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        icon={SvgPaintBrush}
        title={t("branding.title")}
        description={t("branding.description")}
        backButton
      />
      <SettingsLayouts.Body>
        {!context.canAdmin ? (
          <div role="alert">
            <IllustrationContent title={t("common.accessRequired")} />
          </div>
        ) : context.isLoading ||
          branding.isLoading ||
          capabilities.isLoading ? (
          <div role="status">
            <IconLoader />
            <Text>{t("common.loading")}</Text>
          </div>
        ) : !context.cachedData || capabilities.error ? (
          <div role="alert">
            <IllustrationContent title={t("common.unavailable")} />
            <Button
              onClick={() => {
                void context.mutate();
                void capabilities.mutate();
              }}
            >
              {t("common.reload")}
            </Button>
          </div>
        ) : (
          <BrandingForm
            key={`${context.cachedData.tenant_id}:${context.cachedData.user_id}`}
            branding={branding}
            context={context.cachedData}
            enabled={capabilities.data?.branding_enabled === true}
          />
        )}
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
