"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Button, Text } from "@opal/components";
import { usePerson, useRelationships } from "@/lib/people/hooks";
import { peopleHref, type PersonProfile } from "@/lib/people/types";
import {
  Paging,
  PersonCard,
  RequestState,
} from "@/sections/workspace/people/shared";
import EmployeeDirectory from "@/sections/workspace/people/EmployeeDirectory";

interface BranchProps {
  person: PersonProfile;
  path: string[];
  params: string;
}
function ReportBranch({ person, path, params }: BranchProps) {
  const t = useTranslations("workspace.people");
  const [expanded, setExpanded] = useState(false);
  const [offset, setOffset] = useState(0);
  const { data, error, isLoading, mutate } = useRelationships(
    expanded ? person.employee_id : null,
    offset
  );
  const blocked = path.includes(person.employee_id) || path.length >= 16;
  return (
    <li className="workspace-org-node">
      <PersonCard
        person={person}
        href={peopleHref(params, { person: person.employee_id })}
      />
      {blocked ? (
        <Text color="text-03">{t("relationshipWarning")}</Text>
      ) : (
        <Button
          size="sm"
          prominence="tertiary"
          aria-expanded={expanded}
          onClick={() => setExpanded(!expanded)}
        >
          {t(expanded ? "collapse" : "expand")}
        </Button>
      )}
      {expanded && !blocked && (
        <div className="workspace-org-children">
          <RequestState isLoading={isLoading} error={error} retry={mutate} />
          {data && !error && (
            <>
              <ul className="workspace-org-level">
                {data.direct_reports.map((report) => (
                  <ReportBranch
                    key={report.employee_id}
                    person={report}
                    path={[...path, person.employee_id]}
                    params={params}
                  />
                ))}
              </ul>
              {data.warnings.length > 0 && (
                <Text color="text-03">{t("relationshipWarning")}</Text>
              )}
              {data.total_reports === 0 && (
                <Text color="text-03">{t("noReports")}</Text>
              )}
              <Paging
                offset={data.offset}
                limit={data.limit}
                total={data.total_reports}
                onChange={setOffset}
              />
            </>
          )}
        </div>
      )}
    </li>
  );
}

interface OrgChartProps {
  employeeId: string | null;
  params: string;
  query: string;
  departmentId: string | null;
  offset: number;
  onPage: (offset: number) => void;
}
export default function OrgChart({
  employeeId,
  params,
  query,
  departmentId,
  offset,
  onPage,
}: OrgChartProps) {
  const t = useTranslations("workspace.people");
  const person = usePerson(employeeId);
  const relationships = useRelationships(employeeId);
  if (!employeeId)
    return (
      <section>
        <Text>{t("choosePerson")}</Text>
        <EmployeeDirectory
          query={query}
          departmentId={departmentId}
          offset={offset}
          params={params}
          onPage={onPage}
        />
      </section>
    );
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
    <section className="workspace-org-chart" aria-label={t("tabs.chart")}>
      <RequestState
        isLoading={relationships.isLoading}
        error={relationships.error}
        retry={relationships.mutate}
      />
      {relationships.data?.manager ? (
        <div className="workspace-org-manager">
          <PersonCard
            person={relationships.data.manager}
            href={peopleHref(params, {
              person: relationships.data.manager.employee_id,
            })}
          />
        </div>
      ) : (
        !relationships.isLoading &&
        !relationships.error && (
          <Text color="text-03">{t("managerUnavailable")}</Text>
        )
      )}
      {relationships.data && relationships.data.warnings.length > 0 && (
        <Text color="text-03">{t("relationshipWarning")}</Text>
      )}
      <ul className="workspace-org-level">
        <ReportBranch
          key={person.data.employee_id}
          person={person.data}
          path={[]}
          params={params}
        />
      </ul>
    </section>
  );
}
