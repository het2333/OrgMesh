export const PRESENTON_TIME_ZONE =
  process.env.NEXT_PUBLIC_ORGMESH_TIMEZONE || "Asia/Shanghai";

export const PRESENTON_API = "/api/orgmesh/presenton";
export const PRESENTON_JOBS_KEY = `${PRESENTON_API}/jobs`;
export const PRESENTON_LIBRARY_KEY = `${PRESENTON_API}/presentations`;

export interface PresentationStatus {
  available: boolean;
  model_name: string | null;
  provider: string | null;
  image_generation: false;
}

export interface WorkspacePresentation {
  id: string;
  title: string | null;
  n_slides: number;
  created_at: string;
  updated_at: string | null;
  generation_mode: string;
}

export interface PresentationJob {
  id: string;
  status: "pending" | "completed" | "error";
  type: string;
  message: string | null;
  data: {
    presentation_id?: string;
    created_slides?: number;
    remaining_slides?: number;
  } | null;
  created_at: string;
}

export interface PresentationGenerationResponse {
  task_id: string;
}

export interface PresentationAttachment {
  name: string;
  path: string;
  size: number;
}

export function isPresentationId(id: string): boolean {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(
    id
  );
}

export function presentationEditorHref(id: string): string {
  return `/app/tools/presentations/${encodeURIComponent(id)}`;
}
