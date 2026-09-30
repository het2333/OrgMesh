import WorkspaceSearch from "@/sections/workspace/WorkspaceSearch";
import { SEARCH_PARAM_NAMES } from "@/app/app/services/searchParams";

interface PageProps {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}

export default async function Page({ searchParams }: PageProps) {
  const params = await searchParams;
  const rawQuery = params[SEARCH_PARAM_NAMES.SEARCH_QUERY];
  const query = typeof rawQuery === "string" ? rawQuery : "";
  return <WorkspaceSearch key={query} initialQuery={query} />;
}
