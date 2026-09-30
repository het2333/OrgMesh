"use client";

import { useTranslations } from "next-intl";
import { useSWRConfig } from "swr";
import { useFormikContext } from "formik";
import { InputDivider, toast } from "@opal/layouts";
import {
  LLMProviderFormProps,
  LLMProviderName,
  LLMProviderView,
} from "@/lib/languageModels/types";
import { fetchOpenAICompatibleModels } from "@/lib/languageModels/svc";
import {
  useInitialValues,
  buildValidationSchema,
  BaseLLMFormValues,
  withFetchedModels,
} from "@/sections/modals/languageModels/utils";
import { submitProvider } from "@/sections/modals/languageModels/svc";
import { LLMProviderConfiguredSource } from "@/lib/analytics/utils";
import {
  APIBaseField,
  APIKeyField,
  ModelSelectionField,
  DisplayNameField,
  ModelAccessField,
  ModalWrapper,
  useApiBaseSubDescription,
} from "@/sections/modals/languageModels/shared";
import { refreshLlmProviderCaches } from "@/lib/languageModels/cache";
import ModelCapabilityCheck from "@/sections/modals/languageModels/ModelCapabilityCheck";

export interface OpenAICompatiblePreset {
  name: string;
  apiBase: string;
  models: string[];
}

interface OpenAICompatibleModalInternalsProps {
  existingLlmProvider: LLMProviderView | undefined;
  isOnboarding: boolean;
  apiKeyRequired: boolean;
}

function OpenAICompatibleModalInternals({
  existingLlmProvider,
  isOnboarding,
  apiKeyRequired,
}: OpenAICompatibleModalInternalsProps) {
  const t = useTranslations("admin.languageModels.modals");
  const formikProps = useFormikContext<BaseLLMFormValues>();
  const apiBaseSubDescription = useApiBaseSubDescription(
    t("openAiCompatible.apiBaseField.description"),
    t("openAiCompatible.apiBaseField.learnMore")
  );

  const isFetchDisabled = !formikProps.values.api_base;

  const handleFetchModels = async () => {
    const { models, error } = await fetchOpenAICompatibleModels({
      api_base: formikProps.values.api_base || "",
      api_key: formikProps.values.api_key || undefined,
      provider_id: existingLlmProvider?.id ?? undefined,
    });
    if (error) {
      throw new Error(error);
    }
    formikProps.setValues(withFetchedModels(models));
  };

  return (
    <>
      <APIBaseField
        subDescription={apiBaseSubDescription}
        placeholder="http://localhost:8000/v1"
      />

      <APIKeyField
        optional={!apiKeyRequired}
        subDescription={t("openAiCompatible.apiKeyField.description")}
      />
      <ModelCapabilityCheck
        existingLlmProvider={existingLlmProvider}
        apiKeyRequired={apiKeyRequired}
      />

      {!isOnboarding && (
        <>
          <InputDivider />
          <DisplayNameField />
        </>
      )}

      <InputDivider />
      <ModelSelectionField
        shouldShowAutoUpdateToggle={false}
        onRefetch={isFetchDisabled ? undefined : handleFetchModels}
      />

      {!isOnboarding && (
        <>
          <InputDivider />
          <ModelAccessField />
        </>
      )}
    </>
  );
}

export default function OpenAICompatibleModal({
  variant = "llm-configuration",
  existingLlmProvider,
  shouldMarkAsDefault,
  onOpenChange,
  onSuccess,
  analyticsSource,
  preset,
}: LLMProviderFormProps & { preset?: OpenAICompatiblePreset }) {
  const t = useTranslations("admin.languageModels.modals");
  const isOnboarding = variant === "onboarding";
  const { mutate } = useSWRConfig();

  const onClose = () => onOpenChange?.(false);

  const initialValues = useInitialValues(
    isOnboarding,
    LLMProviderName.OPENAI_COMPATIBLE,
    existingLlmProvider
  );
  if (preset && !existingLlmProvider) {
    initialValues.name = preset.name;
    initialValues.api_base = preset.apiBase;
    initialValues.is_auto_mode = false;
    initialValues.test_model_name = preset.models[0];
    initialValues.model_configurations = preset.models.map((name) => ({
      name,
      effectiveDisplayName: name,
      is_visible: true,
      max_input_tokens: null,
      supports_image_input: false,
      supports_reasoning: false,
    }));
  }

  const validationSchema = buildValidationSchema(t, isOnboarding, {
    apiBase: true,
    apiKey: Boolean(preset),
  });

  return (
    <ModalWrapper
      providerName={LLMProviderName.OPENAI_COMPATIBLE}
      llmProvider={existingLlmProvider}
      onClose={onClose}
      initialValues={initialValues}
      description={t("openAiCompatible.description")}
      validationSchema={validationSchema}
      onSubmit={async (values, { setSubmitting, setStatus }) => {
        await submitProvider({
          t,
          analyticsSource:
            analyticsSource ??
            (isOnboarding
              ? LLMProviderConfiguredSource.CHAT_ONBOARDING
              : LLMProviderConfiguredSource.ADMIN_PAGE),
          providerName: LLMProviderName.OPENAI_COMPATIBLE,
          values,
          initialValues,
          existingLlmProvider,
          shouldMarkAsDefault,
          setStatus,
          setSubmitting,
          onClose,
          onSuccess: async () => {
            if (onSuccess) {
              await onSuccess();
            } else {
              await refreshLlmProviderCaches(mutate);
              toast.success(
                existingLlmProvider
                  ? t("toasts.providerUpdated")
                  : t("toasts.providerEnabled")
              );
            }
          },
        });
      }}
    >
      <OpenAICompatibleModalInternals
        existingLlmProvider={existingLlmProvider}
        isOnboarding={isOnboarding}
        apiKeyRequired={Boolean(preset)}
      />
    </ModalWrapper>
  );
}
