export interface Department {
  department_id: string;
  name: string | null;
  parent_id: string | null;
}

export interface PersonProfile {
  employee_id: string;
  email: string | null;
  display_name: string | null;
  job_title: string | null;
  avatar_url: string | null;
  manager_id: string | null;
  direct_department_ids: string[];
  departments: Department[];
}

export interface EmployeePage {
  items: PersonProfile[];
  total: number;
  offset: number;
  limit: number;
}

export interface TeamSummary extends Department {
  member_count: number;
}
export interface TeamPage {
  items: TeamSummary[];
  total: number;
  offset: number;
  limit: number;
}
export interface TeamDetail extends TeamSummary {
  members: EmployeePage;
}
export interface PersonRelationships {
  manager: PersonProfile | null;
  direct_reports: PersonProfile[];
  total_reports: number;
  offset: number;
  limit: number;
  warnings: string[];
}

export const PEOPLE_PAGE_SIZE = 20;

export function peopleHref(
  current: string,
  patch: Record<string, string | null>
): "/app/people" | `/app/people?${string}` {
  const params = new URLSearchParams(current);
  for (const [key, value] of Object.entries(patch)) {
    if (value) params.set(key, value);
    else params.delete(key);
  }
  return params.size ? `/app/people?${params.toString()}` : "/app/people";
}

export function pageOffset(value: string | null): number {
  if (!value || !/^\d+$/.test(value)) return 0;
  return Math.min(Number(value), 100000);
}

export function knowledgeHref(person: PersonProfile): `/app/search?${string}` {
  return `/app/search?${new URLSearchParams({ q: person.display_name || person.email || person.employee_id }).toString()}`;
}
