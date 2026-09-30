export const PRESENTON_BASE_PATH = "/presenton";

export function stripPresentonBasePath(path: string): string {
  if (path === PRESENTON_BASE_PATH) return "/";
  return path.startsWith(`${PRESENTON_BASE_PATH}/`)
    ? path.slice(PRESENTON_BASE_PATH.length)
    : path;
}

export function withPresentonBasePath(path: string): string {
  if (!path.startsWith("/") || path.startsWith("//")) return path;
  return `${PRESENTON_BASE_PATH}${stripPresentonBasePath(path)}`;
}

export function getPresentonRenderBaseUrl(value?: string): string {
  const base = (value?.trim() || "http://127.0.0.1:3000").replace(/\/+$/, "");
  return base.endsWith(PRESENTON_BASE_PATH)
    ? base
    : `${base}${PRESENTON_BASE_PATH}`;
}
