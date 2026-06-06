import "server-only";

/** FastAPI origin — server-side only; the browser only ever talks to /api/cg. */
export const backendBaseUrl = (): string =>
  process.env.CG_API_BASE_URL ?? "http://localhost:8000";

export const backendUrl = (path: string): string =>
  `${backendBaseUrl()}/api/v1/${path.replace(/^\/+/, "")}`;
