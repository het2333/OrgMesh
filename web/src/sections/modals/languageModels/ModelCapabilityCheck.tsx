"use client";

import { useEffect, useRef, useState } from "react";
import { useFormikContext } from "formik";
import { useTranslations } from "next-intl";
import { Button, Text } from "@opal/components";
import { LLMProviderView } from "@/lib/languageModels/types";
import { BaseLLMFormValues } from "@/sections/modals/languageModels/utils";

interface CapabilityCheck {
  supported: boolean;
  error: string | null;
}

interface CapabilityReport {
  streaming: CapabilityCheck;
  tool_calling: CapabilityCheck;
}

interface ModelCapabilityCheckProps {
  existingLlmProvider?: LLMProviderView;
  apiKeyRequired?: boolean;
}

export default function ModelCapabilityCheck({
  existingLlmProvider,
  apiKeyRequired = false,
}: ModelCapabilityCheckProps) {
  const t = useTranslations("workspace.domesticModels");
  const { values, setStatus } = useFormikContext<BaseLLMFormValues>();
  const requestEpoch = useRef(0);
  const [report, setReport] = useState<CapabilityReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [checking, setChecking] = useState(false);
  useEffect(() => {
    requestEpoch.current += 1;
    setReport(null);
    setError(null);
  }, [values.api_key, values.api_base, values.test_model_name]);

  async function checkCapabilities() {
    const epoch = requestEpoch.current;
    setChecking(true);
    setStatus({ isTesting: true });
    setError(null);
    setReport(null);
    try {
      const response = await fetch("/api/admin/llm/test/capabilities", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          id: existingLlmProvider?.id,
          provider: "openai_compatible",
          model: values.test_model_name,
          api_base: values.api_base,
          api_key: values.api_key,
          api_key_changed:
            !existingLlmProvider ||
            values.api_key !== existingLlmProvider.api_key,
          custom_config_changed: false,
        }),
      });
      if (!response.ok) {
        const body: { detail?: string } = await response.json();
        throw new Error(body.detail || t("checkFailed"));
      }
      const result: CapabilityReport = await response.json();
      if (requestEpoch.current === epoch) setReport(result);
    } catch (reason) {
      if (requestEpoch.current === epoch) {
        setError(reason instanceof Error ? reason.message : t("checkFailed"));
      }
    } finally {
      setChecking(false);
      setStatus({ isTesting: false });
    }
  }

  return (
    <div className="flex flex-col gap-3 px-4 py-3">
      <Text font="secondary-body" color="text-03">
        {t("checkDescription")}
      </Text>
      <div>
        <Button
          prominence="secondary"
          type="button"
          onClick={checkCapabilities}
          disabled={
            checking ||
            !values.api_base ||
            !values.test_model_name ||
            (apiKeyRequired && !values.api_key && !existingLlmProvider)
          }
        >
          {t(checking ? "checking" : "check")}
        </Button>
      </div>
      {report &&
        (["streaming", "tool_calling"] as const).map((capability) => (
          <div key={capability}>
            <Text
              font="secondary-body"
              color={
                report[capability].supported
                  ? "status-success-05"
                  : "status-error-05"
              }
            >
              {t("checkResult", {
                capability: t(capability),
                result: t(report[capability].supported ? "passed" : "failed"),
              })}
            </Text>
            {report[capability].error && (
              <Text as="p" font="secondary-body" color="text-03">
                {report[capability].error}
              </Text>
            )}
          </div>
        ))}
      {error && (
        <Text font="secondary-body" color="status-error-05">
          {error}
        </Text>
      )}
    </div>
  );
}
