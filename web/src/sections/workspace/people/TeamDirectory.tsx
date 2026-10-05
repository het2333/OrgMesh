"use client";

import { useFormatter, useTranslations } from "next-intl";
import { Button, Text } from "@opal/components";
import { useTeam, useTeams } from "@/lib/people/hooks";
import { peopleHref } from "@/lib/people/types";
import {
  EmptyDirectory,
  Paging,
  PersonCard,
  RequestState,
} from "@/sections/workspace/people/shared";

interface TeamDirectoryProps {
  departmentId: string | null;
  offset: number;
  params: string;
  onPage: (offset: number) => void;
}
function TeamMembers({
  departmentId,
  offset,
  params,
  onPage,
}: TeamDirectoryProps & { departmentId: string }) {
  const t = useTranslations("workspace.people");
  const { data, error, isLoading, mutate } = useTeam(departmentId, offset);
  if (isLoading || error)
    return <RequestState isLoading={isLoading} error={error} retry={mutate} />;
  if (!data) return <EmptyDirectory />;
  return (
    <section>
      <div className="workspace-people-toolbar">
        <Button
          href={peopleHref(params, {
            department: null,
            offset: null,
            person: null,
          })}
          prominence="tertiary"
        >
          {t("allTeams")}
        </Button>
        <Text as="h2" font="heading-h3">
          {data.name || t("unnamedTeam")}
        </Text>
      </div>
      <div className="workspace-people-grid">
        {data.members.items.map((person) => (
          <PersonCard
            key={person.employee_id}
            person={person}
            href={peopleHref(params, { person: person.employee_id })}
          />
        ))}
      </div>
      <Paging
        offset={data.members.offset}
        limit={data.members.limit}
        total={data.members.total}
        onChange={onPage}
      />
    </section>
  );
}

export default function TeamDirectory(props: TeamDirectoryProps) {
  const t = useTranslations("workspace.people");
  const formatter = useFormatter();
  const { data, error, isLoading, mutate } = useTeams(props.offset);
  if (props.departmentId)
    return <TeamMembers {...props} departmentId={props.departmentId} />;
  if (isLoading || error)
    return <RequestState isLoading={isLoading} error={error} retry={mutate} />;
  if (!data?.items.length) return <EmptyDirectory />;
  return (
    <section>
      <div className="workspace-people-grid">
        {data.items.map((team) => (
          <article key={team.department_id} className="workspace-person-card">
            <Button
              href={peopleHref(props.params, {
                department: team.department_id,
                person: null,
                offset: null,
              })}
              prominence="tertiary"
            >
              {team.name || t("unnamedTeam")}
            </Button>
            <Text color="text-03">
              {t("members", { count: formatter.number(team.member_count) })}
            </Text>
          </article>
        ))}
      </div>
      <Paging
        offset={data.offset}
        limit={data.limit}
        total={data.total}
        onChange={props.onPage}
      />
    </section>
  );
}
