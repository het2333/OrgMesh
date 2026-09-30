"use client";

import { Text } from "@opal/components";
import { SvgOnyxOctagon } from "@opal/icons";
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
  return (
    <div className={cn("workspace-brand", className)}>
      <div className="workspace-brand-mark">
        <SvgOnyxOctagon size={22} />
      </div>
      {!folded && (
        <div className="flex flex-col">
          <Text font="heading-h3" color="text-05">
            {t("brand")}
          </Text>
          <Text font="figure-small-label" color="text-03">
            {t("poweredBy")}
          </Text>
        </div>
      )}
    </div>
  );
}
