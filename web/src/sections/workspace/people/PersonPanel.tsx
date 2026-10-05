"use client";

import { useTranslations } from "next-intl";
import { Button, Text } from "@opal/components";
import { usePerson, useRelationships } from "@/lib/people/hooks";
import { knowledgeHref, peopleHref } from "@/lib/people/types";
import { PersonCard, RequestState } from "@/sections/workspace/people/shared";

interface PersonPanelProps {
  employeeId: string;
  params: string;
}
export default function PersonPanel({ employeeId, params }: PersonPanelProps) {
  const t = useTranslations("workspace.people");
  const person = usePerson(employeeId);
  const relationships = useRelationships(employeeId);
  if (person.isLoading || person.error)
    return (
      <RequestState
        isLoading={person.isLoading}
        error={person.error}
        retry={person.mutate}
      />
    );
  if (!person.data) return null;
  return (
    <aside className="workspace-person-panel" aria-label={t("profile")}>
      <Button href={peopleHref(params, { person: null })} prominence="tertiary">
        {t("closeProfile")}
      </Button>
      <Text as="h2" font="heading-h3">
        {person.data.display_name || t("unnamed")}
      </Text>
      <Text>{person.data.job_title || t("notProvided")}</Text>
      <Text wordWrap="wrap-anywhere">
        {person.data.email || t("notProvided")}
      </Text>
      {person.data.departments.map((department) => (
        <Button
          key={department.department_id}
          href={peopleHref(params, {
            tab: "teams",
            department: department.department_id,
            person: null,
            offset: null,
          })}
          prominence="tertiary"
        >
          {department.name || t("unnamedTeam")}
        </Button>
      ))}
      <Button href={knowledgeHref(person.data)}>{t("knowledgeSearch")}</Button>
      <Text font="secondary-body" color="text-03">
        {t("knowledgeDescription")}
      </Text>
      <Text as="h3" font="main-ui-action">
        {t("manager")}
      </Text>
      {relationships.isLoading || relationships.error ? (
        <RequestState
          isLoading={relationships.isLoading}
          error={relationships.error}
          retry={relationships.mutate}
        />
      ) : relationships.data?.manager ? (
        <PersonCard
          person={relationships.data.manager}
          href={peopleHref(params, {
            person: relationships.data.manager.employee_id,
          })}
        />
      ) : (
        <Text color="text-03">{t("managerUnavailable")}</Text>
      )}
      <Button
        href={peopleHref(params, {
          tab: "chart",
          person: employeeId,
          offset: null,
        })}
        prominence="secondary"
      >
        {t("openChart")}
      </Button>
    </aside>
  );
}
