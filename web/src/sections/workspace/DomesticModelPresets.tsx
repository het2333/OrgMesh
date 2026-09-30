"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Button, Text } from "@opal/components";
import OpenAICompatibleModal, {
  OpenAICompatiblePreset,
} from "@/sections/modals/languageModels/OpenAICompatibleModal";

const PRESETS = {
  deepseek: {
    name: "DeepSeek",
    apiBase: "https://api.deepseek.com/v1",
    models: ["deepseek-chat"],
  },
  qwen: {
    name: "Qwen",
    apiBase: "https://dashscope.aliyuncs.com/compatible-mode/v1",
    models: ["qwen-plus", "qwen-flash"],
  },
} satisfies Record<string, OpenAICompatiblePreset>;

export default function DomesticModelPresets() {
  const t = useTranslations("workspace.domesticModels");
  const [selected, setSelected] = useState<OpenAICompatiblePreset | null>(null);
  return (
    <div className="flex flex-col gap-4 w-full">
      <div className="flex flex-col gap-2">
        <Text font="heading-h3">{t("title")}</Text>
        <Text font="main-ui-muted" color="text-03">
          {t("description")}
        </Text>
      </div>
      <div className="flex flex-wrap gap-3">
        {Object.entries(PRESETS).map(([id, preset]) => (
          <Button
            key={id}
            prominence="secondary"
            onClick={() => setSelected(preset)}
          >
            {t("configure", { provider: preset.name })}
          </Button>
        ))}
      </div>
      {selected && (
        <OpenAICompatibleModal
          preset={selected}
          onOpenChange={() => setSelected(null)}
        />
      )}
    </div>
  );
}
