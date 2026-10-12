"use client";

import { useTranslations } from "next-intl";
import { useSettings } from "@/lib/settings/hooks";
import {
  DEFAULT_LOGO_SIZE_PX,
  NEXT_PUBLIC_DO_NOT_USE_TOGGLE_OFF_DANSWER_POWERED,
} from "@/lib/constants";
import { cn } from "@opal/utils";
import { Text } from "@opal/components";
import { SvgOnyxLogo, SvgOnyxLogoTyped } from "@opal/logos";

export interface LogoProps {
  folded?: boolean;
  size?: number;
  className?: string;
  // Always render the real Onyx logo, ignoring enterprise white-label settings
  // (custom logo / application name). Used by Onyx-branded surfaces like Craft.
  onyxBranded?: boolean;
}

export function Logo({ folded, size, className, onyxBranded }: LogoProps) {
  const t = useTranslations("common");
  const resolvedSize = size ?? DEFAULT_LOGO_SIZE_PX;
  const { appName, logoUrl } = useSettings();

  if (onyxBranded) {
    return folded ? (
      <SvgOnyxLogo size={resolvedSize} className={cn("shrink-0", className)} />
    ) : (
      <SvgOnyxLogoTyped size={resolvedSize} className={className} />
    );
  }

  const logo = logoUrl ? (
    <div
      className={cn(
        "aspect-square rounded-full overflow-hidden relative shrink-0",
        className
      )}
      style={{ height: resolvedSize }}
    >
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        alt={t("logo.image.alt")}
        src={logoUrl}
        className="object-cover object-center w-full h-full"
      />
    </div>
  ) : (
    <SvgOnyxLogo size={resolvedSize} className={cn("shrink-0", className)} />
  );

  return (
    <div className="flex min-w-0 gap-2">
      {logo}
      {!folded && (
        <div className="flex min-w-0 flex-col">
          <Text font="heading-h3" maxLines={1}>
            {appName}
          </Text>
          {!NEXT_PUBLIC_DO_NOT_USE_TOGGLE_OFF_DANSWER_POWERED && (
            <Text font="secondary-body" color="text-03" maxLines={1}>
              {t("logo.poweredBy.label")}
            </Text>
          )}
        </div>
      )}
    </div>
  );
}
