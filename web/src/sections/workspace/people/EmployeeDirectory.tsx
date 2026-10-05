"use client";

import { usePeople } from "@/lib/people/hooks";
import { peopleHref } from "@/lib/people/types";
import {
  EmptyDirectory,
  Paging,
  PersonCard,
  RequestState,
} from "@/sections/workspace/people/shared";

interface EmployeeDirectoryProps {
  query: string;
  departmentId: string | null;
  offset: number;
  params: string;
  onPage: (offset: number) => void;
}
export default function EmployeeDirectory({
  query,
  departmentId,
  offset,
  params,
  onPage,
}: EmployeeDirectoryProps) {
  const { data, error, isLoading, mutate } = usePeople(
    query,
    departmentId,
    offset
  );
  if (isLoading || error)
    return <RequestState isLoading={isLoading} error={error} retry={mutate} />;
  if (!data?.items.length) return <EmptyDirectory />;
  return (
    <div>
      <div className="workspace-people-grid">
        {data.items.map((person) => (
          <PersonCard
            key={person.employee_id}
            person={person}
            href={peopleHref(params, { person: person.employee_id })}
          />
        ))}
      </div>
      <Paging
        offset={data.offset}
        limit={data.limit}
        total={data.total}
        onChange={onPage}
      />
    </div>
  );
}
