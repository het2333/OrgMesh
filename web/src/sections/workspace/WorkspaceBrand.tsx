"use client";

import { Text } from "@opal/components";
import { useSettings } from "@/lib/settings/hooks";
import { cn } from "@opal/utils";
import type { IconProps } from "@opal/types";
import { useTranslations } from "next-intl";

interface WorkspaceBrandProps extends IconProps {
  folded?: boolean;
}

export default function WorkspaceBrand({
  folded,
  className,
}: WorkspaceBrandProps) {
  const t = useTranslations("workspace");
  const { appName, logoUrl } = useSettings();
  return (
    <div className={cn("workspace-brand", className)}>
      <div className="workspace-brand-mark">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={logoUrl ?? "/orgmesh.svg"}
          alt={appName}
          width={22}
          height={22}
        />
      </div>
      {!folded && (
        <div className="flex min-w-0 flex-col">
          <Text font="heading-h3" color="text-05" maxLines={1}>
            {appName}
          </Text>
          <Text font="figure-small-label" color="text-03">
            {t("poweredBy")}
          </Text>
        </div>
      )}
    </div>
  );
}
