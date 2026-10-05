"use client";

import useSWR from "swr";
import {
  errorHandlingFetcher,
  FetchError,
  isAuthStatusError,
} from "@/lib/fetcher";
import { useUser } from "@/providers/UserProvider";
import type {
  EmployeePage,
  PersonProfile,
  PersonRelationships,
  TeamDetail,
  TeamPage,
} from "@/lib/people/types";

function useDirectory<T>(url: string | null) {
  const { user, isUserLoading } = useUser();
  const owner = isUserLoading ? null : user?.id;
  const result = useSWR<T, FetchError>(
    url && owner ? ([url, owner] as const) : null,
    ([path]: readonly [string, string]) => errorHandlingFetcher<T>(path),
    {
      keepPreviousData: false,
      shouldRetryOnError: false,
      revalidateOnFocus: true,
      refreshInterval: 60000,
    }
  );
  return {
    ...result,
    data: !owner || isAuthStatusError(result.error) ? undefined : result.data,
    isLoading: isUserLoading || result.isLoading,
  };
}

export function usePeople(
  query: string,
  departmentId: string | null,
  offset: number
) {
  const params = new URLSearchParams({
    q: query,
    offset: String(offset),
    limit: "20",
  });
  if (departmentId) params.set("department_id", departmentId);
  return useDirectory<EmployeePage>(`/api/orgmesh/people?${params.toString()}`);
}
export function usePerson(employeeId: string | null) {
  return useDirectory<PersonProfile>(
    employeeId ? `/api/orgmesh/people/${encodeURIComponent(employeeId)}` : null
  );
}
export function useTeams(offset = 0, limit = 20) {
  return useDirectory<TeamPage>(
    `/api/orgmesh/teams?offset=${offset}&limit=${limit}`
  );
}
export function useTeam(departmentId: string | null, offset = 0) {
  return useDirectory<TeamDetail>(
    departmentId
      ? `/api/orgmesh/teams/${encodeURIComponent(departmentId)}?offset=${offset}&limit=20`
      : null
  );
}
export function useRelationships(employeeId: string | null, offset = 0) {
  return useDirectory<PersonRelationships>(
    employeeId
      ? `/api/orgmesh/people/${encodeURIComponent(employeeId)}/relationships?offset=${offset}&limit=20`
      : null
  );
}
