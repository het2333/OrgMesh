"use client";

import { useEffect, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { Button, InputTypeIn, Text } from "@opal/components";
import { useTeams } from "@/lib/people/hooks";
import { pageOffset, peopleHref } from "@/lib/people/types";
import EmployeeDirectory from "@/sections/workspace/people/EmployeeDirectory";
import PersonPanel from "@/sections/workspace/people/PersonPanel";
import TeamDirectory from "@/sections/workspace/people/TeamDirectory";
import OrgChart from "@/sections/workspace/people/OrgChart";
import { Paging, RequestState } from "@/sections/workspace/people/shared";

interface DepartmentFilterProps {
  selected: string | null;
  onChange: (department: string | null) => void;
}
function DepartmentFilter({ selected, onChange }: DepartmentFilterProps) {
  const t = useTranslations("workspace.people");
  const [offset, setOffset] = useState(0);
  const { data, isLoading, error, mutate } = useTeams(offset, 100);
  return (
    <div
      className="workspace-people-filters"
      aria-label={t("departmentFilter")}
    >
      <Button
        prominence={selected ? "tertiary" : "secondary"}
        onClick={() => onChange(null)}
      >
        {t("allTeams")}
      </Button>
      <RequestState isLoading={isLoading} error={error} retry={mutate} />
      {data?.items.map((team) => (
        <Button
          key={team.department_id}
          prominence={
            selected === team.department_id ? "secondary" : "tertiary"
          }
          aria-pressed={selected === team.department_id}
          onClick={() => onChange(team.department_id)}
        >
          {team.name || t("unnamedTeam")}
        </Button>
      ))}
      {data && data.total > 100 && (
        <Paging
          offset={offset}
          limit={100}
          total={data.total}
          onChange={setOffset}
        />
      )}
    </div>
  );
}

export default function PeopleWorkspace() {
  const t = useTranslations("workspace.people");
  const router = useRouter();
  const pathname = usePathname();
  const search = useSearchParams();
  const params = search.toString();
  const rawTab = search.get("tab");
  const tab = rawTab === "teams" || rawTab === "chart" ? rawTab : "employees";
  const query = (search.get("q") || "").slice(0, 200);
  const department = search.get("department");
  const person = search.get("person");
  const offset = pageOffset(search.get("offset"));
  const [draft, setDraft] = useState(query);
  useEffect(() => setDraft(query), [query]);

  function navigate(patch: Record<string, string | null>) {
    if (pathname === "/app/people")
      router.push(peopleHref(params, patch), { scroll: false });
  }
  function changePage(next: number) {
    navigate({ offset: next ? String(next) : null });
  }

  return (
    <main className="workspace-people">
      <header className="workspace-people-header">
        <Text as="h1" font="heading-h2">
          {t("title")}
        </Text>
        <Text color="text-03">{t("description")}</Text>
      </header>
      <nav className="workspace-people-tabs" aria-label={t("title")}>
        {(["employees", "teams", "chart"] as const).map((value) => (
          <Button
            key={value}
            prominence={tab === value ? "primary" : "tertiary"}
            aria-pressed={tab === value}
            onClick={() =>
              navigate({
                tab: value === "employees" ? null : value,
                offset: null,
                person: null,
              })
            }
          >
            {t(`tabs.${value}`)}
          </Button>
        ))}
      </nav>
      {tab !== "teams" && (
        <>
          <form
            role="search"
            className="workspace-people-search"
            onSubmit={(event) => {
              event.preventDefault();
              navigate({ q: draft.trim() || null, offset: null, person: null });
            }}
          >
            <InputTypeIn
              searchIcon
              aria-label={t("search.label")}
              placeholder={t("search.placeholder")}
              value={draft}
              maxLength={200}
              onChange={(event) => setDraft(event.target.value)}
            />
            <Button type="submit">{t("search.submit")}</Button>
          </form>
          <DepartmentFilter
            selected={department}
            onChange={(value) =>
              navigate({ department: value, offset: null, person: null })
            }
          />
        </>
      )}
      <div className="workspace-people-body">
        <div className="workspace-people-results">
          {tab === "employees" ? (
            <EmployeeDirectory
              query={query}
              departmentId={department}
              offset={offset}
              params={params}
              onPage={changePage}
            />
          ) : tab === "teams" ? (
            <TeamDirectory
              departmentId={department}
              offset={offset}
              params={params}
              onPage={changePage}
            />
          ) : (
            <OrgChart
              employeeId={person}
              query={query}
              departmentId={department}
              offset={offset}
              params={params}
              onPage={changePage}
            />
          )}
        </div>
        {person && tab !== "chart" && (
          <PersonPanel key={person} employeeId={person} params={params} />
        )}
      </div>
    </main>
  );
}
