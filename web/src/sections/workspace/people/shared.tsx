"use client";

import { useFormatter, useTranslations } from "next-intl";
import { Button, Text } from "@opal/components";
import { IllustrationContent } from "@opal/layouts";
import {
  SvgArrowLeft,
  SvgArrowRight,
  SvgRefreshCw,
  SvgUsers,
} from "@opal/icons";
import type { PersonProfile } from "@/lib/people/types";

interface RequestStateProps {
  isLoading: boolean;
  error: unknown;
  retry: () => void;
}
export function RequestState({ isLoading, error, retry }: RequestStateProps) {
  const t = useTranslations("workspace.people");
  if (error)
    return (
      <div role="alert" className="workspace-people-state">
        <IllustrationContent
          illustration={SvgUsers}
          title={t("error.title")}
          description={t("error.description")}
        />
        <Button
          icon={SvgRefreshCw}
          onClick={() => {
            void retry();
          }}
        >
          {t("retry")}
        </Button>
      </div>
    );
  if (isLoading)
    return (
      <div role="status" className="workspace-people-state">
        <Text>{t("loading")}</Text>
      </div>
    );
  return null;
}

export function EmptyDirectory() {
  const t = useTranslations("workspace.people");
  return (
    <div className="workspace-people-state">
      <IllustrationContent
        illustration={SvgUsers}
        title={t("empty.title")}
        description={t("empty.description")}
      />
    </div>
  );
}

interface PersonCardProps {
  person: PersonProfile;
  href: string;
}
export function PersonCard({ person, href }: PersonCardProps) {
  const t = useTranslations("workspace.people");
  return (
    <article className="workspace-person-card">
      {person.avatar_url && (
        <img
          src={person.avatar_url}
          alt=""
          referrerPolicy="no-referrer"
          className="workspace-person-avatar"
        />
      )}
      <Button href={href} prominence="tertiary">
        {person.display_name || t("unnamed")}
      </Button>
      <Text font="secondary-body" color="text-03">
        {person.job_title || t("notProvided")}
      </Text>
      <Text font="secondary-body" wordWrap="wrap-anywhere">
        {person.email || t("notProvided")}
      </Text>
      {person.departments.map((department) => (
        <Text
          key={department.department_id}
          font="secondary-body"
          color="text-03"
        >
          {department.name || t("unnamedTeam")}
        </Text>
      ))}
    </article>
  );
}

interface PagingProps {
  offset: number;
  limit: number;
  total: number;
  onChange: (offset: number) => void;
}
export function Paging({ offset, limit, total, onChange }: PagingProps) {
  const t = useTranslations("workspace.people");
  const formatter = useFormatter();
  return (
    <div className="workspace-people-paging">
      <Button
        icon={SvgArrowLeft}
        prominence="tertiary"
        disabled={offset === 0}
        onClick={() => onChange(Math.max(0, offset - limit))}
      >
        {t("previous")}
      </Button>
      <Text font="secondary-body">
        {t("page", {
          page: formatter.number(Math.floor(offset / limit) + 1),
          total: formatter.number(total),
        })}
      </Text>
      <Button
        icon={SvgArrowRight}
        prominence="tertiary"
        disabled={offset + limit >= total || offset + limit > 100000}
        onClick={() => onChange(offset + limit)}
      >
        {t("next")}
      </Button>
    </div>
  );
}
